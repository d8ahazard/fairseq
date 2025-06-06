#!/usr/bin/env python3 -u
# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
import os

import hydra
import torch
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf, open_dict

from fairseq import distributed_utils, metrics
from fairseq.dataclass.configs import FairseqConfig
from fairseq.dataclass.initialize import add_defaults, hydra_init
from fairseq.utils import reset_logging
from fairseq_cli.train import main as pre_main

logger = logging.getLogger("fairseq_cli.hydra_train")


@hydra.main(version_base=None, config_path=os.path.join("..", "fairseq", "config"), config_name="config")
def hydra_main(cfg: FairseqConfig) -> float:
    _hydra_main(cfg)


def _hydra_main(cfg: FairseqConfig, **kwargs) -> float:
    add_defaults(cfg)

    if cfg.common.reset_logging:
        reset_logging()  # Hydra hijacks logging, fix that
    else:
        # check if directly called or called through hydra_main
        if HydraConfig.initialized():
            with open_dict(cfg):
                # make hydra logging work with ddp (see # see https://github.com/facebookresearch/hydra/issues/1126)
                cfg.job_logging_cfg = OmegaConf.to_container(
                    HydraConfig.get().job_logging, resolve=True
                )

    # Create the config with proper object handling in omegaconf 2.1+
    cfg_dict = OmegaConf.to_container(cfg, resolve=True, enum_to_str=True)
    cfg = OmegaConf.create(cfg_dict, flags={"allow_objects": True})
    OmegaConf.set_struct(cfg, True)

    try:
        if cfg.common.profile:
            with torch.cuda.profiler.profile():
                with torch.autograd.profiler.emit_nvtx():
                    distributed_utils.call_main(cfg, pre_main, **kwargs)
        else:
            distributed_utils.call_main(cfg, pre_main, **kwargs)
    except BaseException as e:
        if not cfg.common.suppress_crashes:
            raise
        else:
            logger.error("Crashed! " + str(e))

    # get best val and return - useful for sweepers
    try:
        best_val = metrics.get_smoothed_value(
            "valid", cfg.checkpoint.best_checkpoint_metric
        )
    except:
        best_val = None

    if best_val is None:
        best_val = float("inf")

    return best_val


def cli_main():
    try:
        import sys
        from hydra.core.config_store import ConfigStore
        
        # Use built-in argparse instead of hydra._internal.utils.get_args
        cfg_name = "config"
        for i, arg in enumerate(sys.argv):
            if arg == "--config-name" and i + 1 < len(sys.argv):
                cfg_name = sys.argv[i + 1]
                break
            elif arg.startswith("--config-name="):
                cfg_name = arg.split("=", 1)[1]
                break
    except:
        logger.warning("Failed to get config name from command line arguments")
        cfg_name = "config"

    hydra_init(cfg_name)
    hydra_main()


if __name__ == "__main__":
    cli_main()
