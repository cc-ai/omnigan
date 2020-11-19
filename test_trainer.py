import atexit
from argparse import ArgumentParser
from copy import deepcopy

from comet_ml import Experiment
from comet_ml.api import API

import omnigan
from omnigan.utils import get_comet_rest_api_key

import logging

logging.basicConfig()
logging.getLogger().setLevel(logging.ERROR)
import traceback


def set_opts(opts, str_nested_key, value):
    """
    Changes an opts with nested keys:
    set_opts(addict.Dict(), "a.b.c", 2) == Dict({"a":{"b": {"c": 2}}})

    Args:
        opts (addict.Dict): opts whose values should be changed
        str_nested_key (str): nested keys joined on "."
        value (any): value to set to the nested keys of opts
    """
    keys = str_nested_key.split(".")
    o = opts
    for k in keys[:-1]:
        o = o[k]
    o[keys[-1]] = value


def set_conf(opts, conf):
    """
    Updates opts according to a test scenario's configuration dict.
    Ignores all keys starting with "__" which are used for the scenario
    but outside the opts

    Args:
        opts (addict.Dict): trainer options
        conf (dict): scenario's configuration
    """
    for k, v in conf.items():
        if k.startswith("__"):
            continue
        set_opts(opts, k, v)


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


class Colors:
    def _r(self, key, *args):
        return f"{key}{' '.join(args)}{bcolors.ENDC}"

    def ob(self, *args):
        return self._r(bcolors.OKBLUE, *args)

    def w(self, *args):
        return self._r(bcolors.WARNING, *args)

    def og(self, *args):
        return self._r(bcolors.OKGREEN, *args)

    def f(self, *args):
        return self._r(bcolors.FAIL, *args)

    def b(self, *args):
        return self._r(bcolors.BOLD, *args)

    def u(self, *args):
        return self._r(bcolors.UNDERLINE, *args)


def comet_handler(exp, api):
    def sub_handler():
        p = Colors()
        print()
        print(p.b(p.w("Deleting comet experiment")))
        api.delete_experiment(exp.get_key())

    return sub_handler


def print_start(desc):
    p = Colors()
    cdesc = p.b(p.ob(desc))
    title = "|  " + cdesc + "  |"
    line = "-" * (len(desc) + 6)
    print(f"{line}\n{title}\n{line}")


def print_end(desc):
    p = Colors()
    cdesc = p.b(p.og(desc))
    title = "|  " + cdesc + "  |"
    line = "-" * (len(desc) + 6)
    print(f"{line}\n{title}\n{line}")


def delete_on_exit(exp):
    """
    Registers a callback to delete the comet exp at program exit

    Args:
        exp (comet_ml.Experiment): The exp to delete
    """
    rest_api_key = get_comet_rest_api_key()
    api = API(api_key=rest_api_key)
    atexit.register(comet_handler(exp, api))


if __name__ == "__main__":

    # -----------------------------
    # -----  Parse Arguments  -----
    # -----------------------------
    parser = ArgumentParser()
    parser.add_argument("--no_delete", action="store_true", default=False)
    parser.add_argument("--no_end_to_end", action="store_true", default=False)
    args = parser.parse_args()

    # --------------------------------------
    # -----  Create global experiment  -----
    # --------------------------------------

    global_exp = Experiment(project_name="omnigan-test", display_summary_level=0)
    if not args.no_delete:
        delete_on_exit(global_exp)

    # prompt util for colors
    prompt = Colors()

    # -------------------------------------
    # -----  Base Test Scenario Opts  -----
    # -------------------------------------
    base_opts = omnigan.utils.load_opts()
    base_opts.data.check_samples = False
    base_opts.train.fid.n_images = 5
    base_opts.comet.display_size = 5
    base_opts.tasks = ["m", "s", "d"]
    base_opts.domains = ["r", "s"]
    base_opts.data.loaders.num_workers = 4
    base_opts.data.loaders.batch_size = 2
    base_opts.data.max_samples = 9
    base_opts.train.epochs = 1
    if isinstance(base_opts.data.transforms[-1].new_size, int):
        base_opts.data.transforms[-1].new_size = 256
    else:
        base_opts.data.transforms[-1].new_size.default = 256

    # --------------------------------------
    # -----  Configure Test Scenarios  -----
    # --------------------------------------

    # override any nested key in opts
    # create scenario-specific variables with __key
    # ALWAYS specify a __doc key to describe your scenario
    test_scenarios = [
        {"__comet": False, "__doc": "MSD no exp"},
        {"__doc": "MSD with exp"},
        {"tasks": ["p"], "domains": ["rf"], "__doc": "Painter"},
        {
            "tasks": ["m", "s", "d", "p"],
            "domains": ["rf", "r", "s"],
            "__doc": "MSDP no End-to-end",
        },
        {
            "tasks": ["m", "s", "d", "p"],
            "domains": ["rf", "r", "s"],
            "__pl4m": True,
            "__doc": "MSDP with End-to-end",
        },
    ]

    n_confs = len(test_scenarios)

    fails = []
    successes = []

    # --------------------------------
    # -----  Run Test Scenarios  -----
    # --------------------------------

    for test_idx, conf in enumerate(test_scenarios):
        # copy base scenario opts
        test_opts = deepcopy(base_opts)
        # update with scenario configuration
        set_conf(test_opts, conf)

        # print scenario description
        print_start(
            f"[{test_idx + 1}/{n_confs}] "
            + conf.get("__doc", "WARNING: no __doc for test scenario")
        )
        print()
        print(f"{prompt.b('••  Current Scenario:')}\n{conf}")
        print(prompt.b("•• Execution:\n"))

        # set (or not) experiment
        test_exp = None
        if conf.get("__comet", True):
            test_exp = global_exp

        try:
            # create trainer
            trainer = omnigan.trainer.Trainer(opts=test_opts, comet_exp=test_exp,)
            trainer.functional_test_mode()

            # set (or not) painter loss for masker (= end-to-end)
            if conf.get("__pl4m", False):
                trainer.use_pl4m = True

            # test training procedure
            trainer.setup()
            trainer.train()

            successes.append(test_idx)
        except Exception as e:
            print(e)
            print(traceback.format_exc())
            fails.append(test_idx)
        finally:
            print_end("Done")

    print_end("     -----   Summary   -----     ")
    if len(fails) == 0:
        print("•• All scenarios were successful")
    else:
        print(f"•• {len(successes)} successful tests")
        print(f"•• Failed test indices: {', '.join(map(str, fails))}")
