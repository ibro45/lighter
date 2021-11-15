import sys
from functools import partial
from typing import Callable, List, Optional, Union

import pytorch_lightning as pl
import torch
import wandb
from loguru import logger
from torch.nn import Module, ModuleList
from torch.optim import Optimizer
from torch.utils.data import DataLoader, Dataset, Sampler

from lightningbringer.utils import (collate_fn_replace_corrupted, get_name,
                                    preprocess_image, wrap_into_list)


class System(pl.LightningModule):

    def __init__(self,
                 model: Module,
                 batch_size: int,
                 num_workers: int = 0,
                 pin_memory: bool = True,
                 criterion: Optional[Callable] = None,
                 optimizers: Optional[Union[Optimizer, List[Optimizer]]] = None,
                 schedulers: Optional[Union[Callable, List[Callable]]] = None,
                 metrics: Optional[Union[Callable, List[Callable]]] = None,
                 train_dataset: Optional[Union[Dataset, List[Dataset]]] = None,
                 val_dataset: Optional[Union[Dataset, List[Dataset]]] = None,
                 test_dataset: Optional[Union[Dataset, List[Dataset]]] = None,
                 train_sampler: Optional[Sampler] = None,
                 val_sampler: Optional[Sampler] = None,
                 test_sampler: Optional[Sampler] = None,
                 log_input_as: Optional[str] = None,
                 log_target_as: Optional[str] = None,
                 log_pred_as: Optional[str] = None):

        super().__init__()
        self.model = model
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.pin_memory = pin_memory

        self.train_dataset = train_dataset
        self.val_dataset = val_dataset
        self.test_dataset = test_dataset

        self.train_sampler = train_sampler
        self.val_sampler = val_sampler
        self.test_sampler = test_sampler

        self.criterion = criterion
        self.optimizers = wrap_into_list(optimizers)
        self.schedulers = wrap_into_list(schedulers)
        self.metrics = ModuleList(wrap_into_list(metrics))

        self.log_input_as = log_input_as
        self.log_target_as = log_target_as
        self.log_pred_as = log_pred_as

        # Methods `train_dataloader()`and `training_step()` are defined in `self.setup()`.
        # LightningModule checks for them at init, these prevent it from complaining.
        self.train_dataloader = lambda: None
        self.training_step = lambda: None

    def forward(self, x):
        """Forward pass. Allows calling self(x) to do it."""
        return self.model(x)

    def _step(self, batch, batch_idx, mode):
        """Step for all modes ('train', 'val', 'test')

        Args:
            batch (Tuple(torch.Tensor, Any)): output of the DataLoader.
            batch_idx (int): index of the batch. Not using it, but Pytorch Lightning requires it.
            mode (str): mode in which the system is. ['train', 'val', 'test']

        Returns:
            Union[torch.Tensor, None]: returns the calculated loss in training and validation step,
                and None in test step.
        """
        input, target = batch
        pred = self(input)
        target = target

        # When the task is to predict a single value, pred and target dimensions often
        # mismatch - dataloader returns the value with shape (B), while the network
        # return predictions in shape (B, 1), where the second dim is redundant.
        if len(target.shape) == 1 and len(pred.shape) == 2 and pred.shape[1] == 1:
            pred = pred.flatten()

        loss = self.criterion(pred, target.to(pred.dtype)) if mode != "test" else None

        # BCEWithLogitsLoss applies sigmoid internally, so the model shouldn't have
        # sigmoid output layer. However, for correct metric calculation and logging
        # we apply it after having calculated the loss.
        if isinstance(loss, torch.nn.BCEWithLogitsLoss):
            pred = torch.sigmoid(pred)

        loss = self.criterion(pred, target) if mode != "test" else None
        metrics = [metric(pred, target) for metric in self.metrics]

        self._log(mode, input, target, pred, metrics, loss)
        return loss

    def _dataloader(self, mode):
        """Instantiate the dataloader for a mode (train/val/test).
        Includes a collate function that enables the DataLoader to replace
        None's (alias for corrupted examples) in the batch with valid examples.
        To make use of it, write a try-except in your Dataset that handles
        corrupted data by returning None instead.

        Args:
            mode (str): mode for which to create the dataloader. ['train', 'val', 'test']

        Returns:
            torch.utils.data.DataLoader: instantiated DataLoader.
        """
        dataset = getattr(self, f"{mode}_dataset")
        sampler = getattr(self, f"{mode}_sampler")
        # A dataset can return None when a corrupted example occurs. This collate
        # function replaces them with valid examples from the dataset.
        collate_fn = partial(collate_fn_replace_corrupted, dataset=dataset)
        return DataLoader(dataset,
                          sampler=sampler,
                          shuffle=(mode == "train" and sampler is None),
                          batch_size=self.batch_size,
                          num_workers=self.num_workers,
                          pin_memory=self.pin_memory,
                          collate_fn=collate_fn)

    def configure_optimizers(self):
        """LightningModule method. Returns optimizers and, if defined, schedulers."""
        if self.optimizers is None:
            logger.error("Please specify 'optimizers' in the config. Exiting.")
            sys.exit()
        if self.schedulers is None:
            return self.optimizers
        return self.optimizers, self.schedulers

    def setup(self, stage):
        """LightningModule method. Called after initializing but before running the system.
        Here, it checks if the required dataset is provided in the config and sets up
        LightningModule methods for the stage (mode) in which the system is.

        Args:
            stage (str): passed by PyTorch Lightning. ['fit', 'validate', 'test']
                # TODO: update when all stages included
        """
        dataset_required_by_stage = {
            "fit": "train_dataset",
            "validate": "val_dataset",
            "test": "test_dataset"
        }
        dataset_name = dataset_required_by_stage[stage]
        if getattr(self, dataset_name) is None:
            logger.error(f"Please specify '{dataset_name}' in the config. Exiting.")
            sys.exit()

        # Stage-specific PyTorch Lightning methods. Defined dynamically so that the system
        # only has methods used in the stage and for which the configuration was provided.

        # Training methods.
        if stage == "fit":
            self.train_dataloader = partial(self._dataloader, mode="train")
            self.training_step = partial(self._step, mode="train")

        # Validation methods. Required in 'validate' stage and optionally in 'fit' stage.
        if stage == "validate" or (stage == "fit" and self.val_dataset is not None):
            self.val_dataloader = partial(self._dataloader, mode="val")
            self.validation_step = partial(self._step, mode="val")

        # Test methods.
        if stage == "test":
            self.test_dataloader = partial(self._dataloader, mode="test")
            self.test_step = partial(self._step, mode="test")

    def _log(self, mode, input, target, pred, metrics=None, loss=None):
        """Log the data from the system.

        Args:
            mode (str): mode in which the system is. ['train', 'val', 'test']
            input (torch.Tensor): input data to the model.
            target (torch.Tensor): target data (label).
            pred (torch.Tensor): output (prediction) of the model.
            metrics (List[torch.Tensor], optional): model's metrics. Defaults to None.
            loss (torch.Tensor, optional): model's loss. Defaults to None.
        """

        def log_by_type(data, name, data_type, on_step=True, on_epoch=True):
            """Log data according to its type.

            Args:
                data (Any): data to log.
                name (str): the name under which the data will be logged.
                data_type (str): type of the data to be logged.
                    ['scalar', 'image_batch', 'image_single']  # TODO update when there's more
                on_step (bool, optional): Log on step. Defaults to True.
                on_epoch (bool, optional): Log on batch. Defaults to True.
            """
            # Scalars
            if data_type == "scalar":
                self.log(name, data, on_step=on_step, on_epoch=on_epoch)

            # Temporary, https://github.com/PyTorchLightning/pytorch-lightning/issues/6720
            # Images
            elif data_type in ["image_single", "image_batch"]:
                for lgr in self.logger:
                    image = data[0:1] if data_type == "image_single" else data
                    image = preprocess_image(image)
                    if isinstance(lgr, pl.loggers.WandbLogger):
                        # Temporary, log every 50 steps
                        if self.global_step % 50:
                            lgr.experiment.log({name: wandb.Image(image)})
            else:
                logger.error(f"'type' '{data_type}' not supported. Exiting.")
                sys.exit()

        # Loss
        if loss is not None:
            log_by_type(loss, name=f"{mode}/loss", data_type="scalar")

        # Metrics
        if metrics:
            for metric, metric_fn in zip(metrics, self.metrics):
                name = get_name(metric_fn)
                log_by_type(metric, name=f"{mode}/metric_{name}", data_type="scalar")

        # Input, target, pred
        for key, value in {"input": input, "target": target, "pred": pred}.items():
            log_as = getattr(self, f"log_{key}_as")
            if log_as is not None:
                log_by_type(value, name=f"{mode}/{key}", data_type=log_as)
