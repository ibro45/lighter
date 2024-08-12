from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, model_validator
from torch.utils.data import Dataset, Sampler
from torchmetrics import MetricCollection

BaseModel.model_config["arbitrary_types_allowed"] = True
BaseModel.model_config["hide_input_in_errors"] = True


class SubscriptableBaseModel(BaseModel):
    def __getitem__(self, item):
        return getattr(self, item)


# ----- Config schema -----


class ArgsConfigSchema(BaseModel):
    fit: Dict[str, Any] = {}
    validate: Dict[str, Any] = {}
    predict: Dict[str, Any] = {}
    lr_find: Dict[str, Any] = {}
    scale_batch_size: Dict[str, Any] = {}

    @model_validator(mode="after")
    def check_prohibited_args(self):  # pylint: disable=no-self-argument
        prohibited_keys = ["model", "train_loaders", "validation_loaders", "dataloaders", "datamodule"]
        for field in self.model_fields:
            found_keys = [key for key in prohibited_keys if key in getattr(self, field)]
            if found_keys:
                raise ValueError(
                    f"Found the following prohibited argument(s) in 'args#{field}': "
                    f"{found_keys}. Model and datasets should be defined within the 'system'."
                )
        return self


class ConfigSchema(BaseModel):
    _requires_: Optional = None
    project: Optional[str] = None
    vars: Dict[str, Any] = {}
    args: ArgsConfigSchema = ArgsConfigSchema()
    system: Dict[str, Any] = {}
    trainer: Dict[str, Any] = {}


# ----- LighterSystem schema -----


class DatasetSchema(SubscriptableBaseModel):
    train: Optional[Dataset] = None
    val: Optional[Dataset] = None
    test: Optional[Dataset] = None
    predict: Optional[Dataset] = None


class SamplerSchema(SubscriptableBaseModel):
    train: Optional[Sampler] = None
    val: Optional[Sampler] = None
    test: Optional[Sampler] = None
    predict: Optional[Sampler] = None


class CollateFnSchema(SubscriptableBaseModel):
    train: Optional[Callable] = None
    val: Optional[Callable] = None
    test: Optional[Callable] = None
    predict: Optional[Callable] = None


class MetricsSchema(SubscriptableBaseModel):
    train: Optional[Union[Any, List[Any], Dict[str, Any]]] = None
    val: Optional[Union[Any, List[Any], Dict[str, Any]]] = None
    test: Optional[Union[Any, List[Any], Dict[str, Any]]] = None

    @model_validator(mode="after")
    def setup_metrics(self):  # pylint: disable=no-self-argument
        for field in self.model_fields:
            mode_metrics = getattr(self, field)
            if field is not None:
                setattr(self, field, MetricCollection(mode_metrics))
        return self


class ModeSchema(SubscriptableBaseModel):
    train: Optional[Union[Callable, List[Callable]]] = None
    val: Optional[Union[Callable, List[Callable]]] = None
    test: Optional[Union[Callable, List[Callable]]] = None


class DataSchema(SubscriptableBaseModel):
    input: Optional[Union[Callable, List[Callable]]] = None
    target: Optional[Union[Callable, List[Callable]]] = None
    pred: Optional[Union[Callable, List[Callable]]] = None


class PostprocessingSchema(SubscriptableBaseModel):
    batch: ModeSchema = ModeSchema()
    criterion: DataSchema = DataSchema()
    metrics: DataSchema = DataSchema()
    logging: DataSchema = DataSchema()
