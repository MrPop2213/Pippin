import json
import shutil
import subprocess
import os
from collections import OrderedDict

from pippin.config import mkdirs, get_output_loc, get_config
from pippin.task import Task


class DataPrep(Task):  # TODO: Define the location of the output so we can run the lc fitting on it.
    """ Smack the data into something that looks like the simulated data


    """
    def __init__(self, name, output_dir, options, dependencies=None):
        super().__init__(name, output_dir, dependencies=dependencies)
        self.options = options
        self.global_config = get_config()

        self.logfile = os.path.join(self.output_dir, "output.log")
        self.conda_env = self.global_config["DataSkimmer"]["conda_env"]
        self.path_to_task = get_output_loc(self.global_config["DataSkimmer"]["location"])

        self.raw_dir = self.options.get("RAW_DIR")
        self.fits_file = self.options.get("FITS_FILE")
        self.dump_dir = self.options.get("DUMP_DIR", self.output_dir)

        self.genversion = os.path.basename(self.raw_dir)
        self.job_name = f"DATAPREP_{self.name}"

        self.output["genversion"] = self.genversion
        self.output["photometry_dir"] = get_output_loc(self.raw_dir)
        self.output["skimmed_photometry_dir"] = os.path.join(self.output_dir, self.genversion)

        self.slurm = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --time=1:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --partition=broadwl
#SBATCH --output={log_file}
#SBATCH --account=pi-rkessler
#SBATCH --mem=24GB

source activate {conda_env}
echo `which python`
cd {path_to_task}
python skim_data_lcs.py {command_opts}
"""

    def _get_types(self):
        """ Load the data types from json file """
        filename = os.path.join(self.dump_dir, "sntypes.json")
        if os.path.exists(filename):
            self.logger.debug(f"Loading types from {filename}")
            with open(filename) as f:
                list_types = json.load(f)

                def key(x):
                    if x[1].lower() == "ia":
                        return 0
                    else:
                        return 99999999 + x[0]

                sorted_types = sorted(list_types, key=key)
                types = OrderedDict(sorted_types)
                self.logger.debug(f"Found types {json.dumps(types)}")
                return types
        else:
            self.logger.warn(f"Types not found at {filename}, why is this the case???")

    def _check_completion(self, squeue):
        if os.path.exists(self.done_file):
            self.logger.debug(f"Done file found at f{self.done_file}")
            with open(self.done_file) as f:
                if "FAILURE" in f.read():
                    self.logger.info(f"Done file reported failure. Check output log {self.logfile}")
                    return Task.FINISHED_FAILURE
                else:
                    self.output["types"] = self._get_types()
                    return Task.FINISHED_SUCCESS
        return 1  # The number of CPUs being utilised

    def _run(self, force_refresh):
        command_opts = f"--raw_dir {get_output_loc(self.raw_dir)} " if self.raw_dir is not None else ""
        if self.raw_dir:
            self.logger.debug(f"Running data prep on data directory {self.raw_dir}")
        else:
            self.logger.error(f"Data prep task {self.name} has no RAW_DIR set, please point it to some photometry!")
            return False

        command_opts += f"--fits_file {get_output_loc(self.fits_file)} " if self.fits_file is not None else ""
        command_opts += f"--dump_dir {get_output_loc(self.dump_dir)} " if self.dump_dir is not None else ""
        command_opts += f"--done_file {get_output_loc(self.done_file)} "
        command_opts += f"--cut_version {self.genversion}"

        format_dict = {
            "job_name": self.job_name,
            "log_file": self.logfile,
            "conda_env": self.conda_env,
            "path_to_task": self.path_to_task,
            "command_opts": command_opts
        }

        final_slurm = self.slurm.format(**format_dict)

        new_hash = self.get_hash_from_string(final_slurm)
        old_hash = self.get_old_hash()

        if force_refresh or new_hash != old_hash:
            self.logger.debug("Regenerating and launching task")
            shutil.rmtree(self.output_dir, ignore_errors=True)
            mkdirs(self.output_dir)
            self.save_new_hash(new_hash)
            slurm_output_file = os.path.join(self.output_dir, "slurm.job")
            with open(slurm_output_file, "w") as f:
                f.write(final_slurm)
            self.logger.info(f"Submitting batch job for data prep")
            subprocess.run(["sbatch", slurm_output_file], cwd=self.output_dir)
        else:
            self.logger.info("Hash check passed, not rerunning")
        return True