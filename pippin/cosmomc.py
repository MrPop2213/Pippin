import shutil
import subprocess
import os

from pippin.config import mkdirs, get_config
from pippin.create_cov import CreateCov
from pippin.task import Task


class CosmoMC(Task):  # TODO: Define the location of the output so we can run the lc fitting on it.
    """ Run cosmomc given an ini file

    CONFIGURATION
    =============

    COSMOMC:
        label:
            MASK_CREATE_COV: mask  # partial match
            OPTS:  # Options
                INI: sn_cmb_omw  # should match the filename of at a file in the pippin/data_files/cosmomc_templates directory
                COVOPTS: [ALL, NOSYS]  # Optional, covopts from CREATE_COV step to run against. If you leave this blank, you get them all. Exact matching.
                NUM_WALKERS: 4  # Optional, defaults to four.

    OUTPUTS
    =======

    chain_dir : directory where cosmomc chains will be located
    num_walkers : number of output chains
    covopts : list of covopts
    labels : a list of the names generated by combining task name with covopt name. eg SN_CMB_OMW_ALL or SN_CMB_OMW_NOSYS
    base_dict : a map from covopt label to a base files which you can add .params to
    chain_dict : a map from covopt label to a .txt file to be loaded in
    param_dict : a map from covopt label to a text file listing param names and latex label
    cosmology_params : a list of cosmology parameter names output by cosmomc that we really care about

    """
    def __init__(self, name, output_dir, options, dependencies=None):
        super().__init__(name, output_dir, dependencies=dependencies)
        self.options = options
        self.global_config = get_config()

        self.job_name = f"cosmomc_{name}"
        self.logfile = os.path.join(self.output_dir, "output.log")

        self.path_to_cosmomc = self.global_config["CosmoMC"]["location"]

        self.create_cov_dep = self.get_dep(CreateCov)
        print("AAAAAAAAAAAAAAAAA ", self.options)
        avail_cov_opts = self.create_cov_dep.output["covopts"]

        self.covopts = options.get("COVOPTS") or list(avail_cov_opts.keys())
        self.covopts_numbers = [avail_cov_opts[k] for k in self.covopts]
        self.num_jobs = len(self.covopts)
        self.ini_prefix = options.get("INI")
        self.num_walkers = options.get("NUM_WALKERS", 4)
        self.chain_dir = os.path.join(self.output_dir, "chains")

        self.labels = [self.name + "_" + c for c in self.covopts]
        self.ini_files = [f"{self.ini_prefix}_{num}.ini" for num in self.covopts_numbers]
        self.done_files = [f"done_{num}.txt" for num in self.covopts_numbers]
        self.param_dict = {l: os.path.join(self.chain_dir, i.replace(".ini", ".paramnames")) for l, i in zip(self.covopts, self.ini_files)}
        self.chain_dict = {l: os.path.join(self.chain_dir, i.replace(".ini", f"_{n + 1}.txt")) for l, i in zip(self.covopts, self.ini_files) for n in range(self.num_walkers)}
        self.base_dict = {l: os.path.join(self.chain_dir, i.replace(".ini", "")) for l, i in zip(self.covopts, self.ini_files) for n in range(self.num_walkers)}
        self.output["chain_dir"] = self.chain_dir
        self.output["param_dict"] = self.param_dict
        self.output["chain_dict"] = self.chain_dict
        self.output["base_dict"] = self.chain_dict
        self.output["covopts"] = self.covopts
        final = self.ini_prefix.split("_")[-1]
        ps = {
            "omw": ["omegam", "w"],
            "omol": ["omegam", "omegal"],
            "wnu": ["w", "nu"],
            "wwa": ["w", "wa"],
        }
        self.output["cosmology_params"] = ps[final]

        self.slurm = """#!/bin/bash
#SBATCH --job-name={job_name}
#SBATCH --time=12:00:00
#SBATCH --nodes=1
#SBATCH --ntasks={num_walkers}
#SBATCH --array=1-{num_jobs}
#SBATCH --cpus-per-task=1
#SBATCH --partition=broadwl
#SBATCH --output={log_file}
#SBATCH --account=pi-rkessler
#SBATCH --mem=10GB

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK

PARAMS=`expr ${{SLURM_ARRAY_TASK_ID}} - 1`
INI_FILES=({ini_files})
DONE_FILES=({done_files})

cd {output_dir}
mpirun {path_to_cosmomc}/cosmomc ${INI_FILES[$PARAMS]}

if [ $? -eq 0 ]; then
    echo "SUCCESS" > ${DONE_FILES[$PARAMS]}
else
    echo "FAILURE" > ${DONE_FILES[$PARAMS]}
fi
"""

    def _check_completion(self, squeue):
        if os.path.exists(self.done_file):
            self.logger.debug(f"Done file found at f{self.done_file}")
            with open(self.done_file) as f:
                if "FAILURE" in f.read():
                    self.logger.error(f"Done file reported failure. Check output log {self.logfile}")
                    return Task.FINISHED_FAILURE
                else:
                    return Task.FINISHED_SUCCESS
        else:
            all_files = True
            for d in self.done_files:
                if os.path.exists(d):
                    with open(d) as f:
                        if "FAILURE" in f.read():
                            self.logger.error(f"Done file {d} reported failure. Check output log {self.logfile}")
                            return Task.FINISHED_FAILURE
                else:
                    all_files = False
            if all_files:
                # Check that the expected outputs exist to
                for file in self.chain_dict.values():
                    if not os.path.exists(file):
                        self.logger.error(f"No chain found at {file}")
                        return Task.FINISHED_FAILURE
                for file in self.param_dict.values():
                    if not os.path.exists(file):
                        self.logger.error(f"No paramnames file at {file}")
                        return Task.FINISHED_FAILURE
                with open(self.done_file, "w") as f:
                    f.write("SUCCESS")
                return Task.FINISHED_SUCCESS
        return 4 * self.num_jobs

    def get_ini_file(self):
        mkdirs(self.chain_dir)
        directory = self.create_cov_dep.output["ini_dir"]

        input_files = []
        for file in self.ini_files:
            path = os.path.join(directory, file)
            if not os.path.exists(path):
                self.logger.error(f"Cannot find the file {path}, make sure you specified a correct INI string matching an existing template")
                return None
            with open(path) as f:
                input_files.append(f.read().format(**{
                    "path_to_cosmomc": self.path_to_cosmomc,
                    "ini_dir": self.create_cov_dep.output["ini_dir"],
                    "root_dir": self.chain_dir
                }))

        return input_files

    def _run(self, force_refresh):

        ini_filecontents = self.get_ini_file()
        if ini_filecontents is None:
            return False

        format_dict = {
            "job_name": self.job_name,
            "log_file": self.logfile,
            "done_files": " ".join(self.done_files),
            "path_to_cosmomc": self.path_to_cosmomc,
            "output_dir": self.output_dir,
            "ini_files": " ".join(self.ini_files),
            "num_walkers": self.num_walkers

        }
        final_slurm = self.slurm.format(**format_dict)

        new_hash = self.get_hash_from_string(final_slurm + " ".join(ini_filecontents))
        old_hash = self.get_old_hash()

        if force_refresh or new_hash != old_hash:
            self.logger.debug("Regenerating and launching task")
            shutil.rmtree(self.output_dir, ignore_errors=True)
            mkdirs(self.output_dir)
            self.save_new_hash(new_hash)
            slurm_output_file = os.path.join(self.output_dir, "slurm.job")
            with open(slurm_output_file, "w") as f:
                f.write(final_slurm)
            for file, content in zip(self.ini_files, ini_filecontents):
                filepath = os.path.join(self.output_dir, file)
                with open(filepath, "w") as f:
                    f.write(content)

            self.logger.info(f"Submitting batch job for data prep")
            subprocess.run(["sbatch", slurm_output_file], cwd=self.output_dir)
        else:
            self.logger.info("Hash check passed, not rerunning")
        return True
