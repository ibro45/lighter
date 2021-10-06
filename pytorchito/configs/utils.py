import sys
import importlib
from pathlib import Path

from loguru import logger
from omegaconf import OmegaConf


def init_config(omegaconf_args, config_class):
    """Loads a YAML config file specified with 'config' key in command line arguments,
    type checks it against the config's dataclass, and parses the remaining comand line
    arguments as config options.

    Args:
        omegaconf_args (list): list of command line arguments.
        config_class (dataclass): config's dataclass, used for static type checking by OmegaConf.

    Returns:
        omegaconf.DictConfig: configuration
    """

    cli = OmegaConf.from_dotlist(omegaconf_args)
    assert "config" in cli, "Please provide path to a YAML config using `config` option."

    conf = OmegaConf.load(cli.pop("config"))
    # Merge conf and the conf dataclass for type checking
    conf = OmegaConf.merge(OmegaConf.structured(config_class), conf)
    # Merge yaml conf and cli conf
    conf = OmegaConf.merge(conf, cli)

    # Allows the framework to find user-defined, project-specific, classes and their configs
    if conf.project:
        import_project_as_module(conf.project)

    return conf


def import_project_as_module(project):
    """Given the path to the project, import it as a module with name 'project'.

    Args:
        project (str): path to the project that will be loaded as module.
    """
    assert isinstance(project, str), "project needs to be a str path"

    # Import project as module with name "project", https://stackoverflow.com/a/41595552
    project_path = Path(project).resolve() / "__init__.py"
    assert project_path.is_file(), f"No `__init__.py` in project `{project_path}`."
    spec = importlib.util.spec_from_file_location("project", str(project_path))
    project_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project_module)
    sys.modules["project"] = project_module

    logger.info(f"Project directory {project} added as a module with name 'project'.")
