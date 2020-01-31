import yaml
import inspect
import logging
import hashlib
import os
import shutil
import stat


def singleton(fn):
    instance = None

    def get(*args, **kwargs):
        nonlocal instance
        if instance is None:
            instance = fn(*args, **kwargs)
        return instance

    return get


def merge_dict(original, extra):

    for key, value in extra.items():
        if isinstance(value, dict):
            node = original.setdefault(key, {})
            merge_dict(node, value)
        elif isinstance(value, list):
            original[key] = value + original[key]
        else:
            original[key] = value
    return original


@singleton
def get_config(initial_path=None, overwrites=None):
    this_dir = os.path.abspath(os.path.dirname(inspect.stack()[0][1]))
    if initial_path is None:
        filename = os.path.abspath(os.path.join(this_dir, "..", "cfg.yml"))
    else:
        filename = initial_path
    assert os.path.exists(filename), f"Config location {filename} cannot be found."
    with open(filename, "r") as f:
        config = yaml.safe_load(f)
    print("AAA ", config)

    if overwrites is not None:
        config = merge_dict(config, overwrites)

    for i, path in enumerate(config["DATA_DIRS"]):
        updated = get_data_loc([this_dir], path)
        if updated is None:
            logging.error(f"Data dir {path} cannot be resolved!")
            assert updated is not None
        config["DATA_DIRS"][i] = updated

    print("BBB ", config)
    return config


def get_output_dir():
    output_dir = get_config()["OUTPUT"]["output_dir"]
    if "$" in output_dir:
        output_dir = os.path.expandvars(output_dir)
        if "$" in output_dir:
            raise ValueError(f"Could not resolve variable in path: {output_dir}")
    if not output_dir.startswith("/"):
        output_dir = os.path.abspath(os.path.dirname(inspect.stack()[0][1]) + "/../" + output_dir)
    return output_dir


def get_data_loc(data_dirs, path):
    if "$" in path:
        path = os.path.expandvars(path)
        if "$" in path:
            logging.error(f"Unable to resolve the variable in {path}, please check to see if it is set in your environment")
            return None
        return path
    if path.startswith("/"):
        if not os.path.exists(path):
            logging.error(f"Got an absolute path that doesn't exist: {path}")
            return None
        return path
    else:
        for data_dir in data_dirs:
            new_path = os.path.join(data_dir, path)
            if os.path.exists(new_path):
                return new_path
        logging.error(f"Unable to find relative path {path} when searching through the data directories: {data_dirs}")
        return None


def get_output_loc(path):
    if "$" in path:
        path = os.path.expandvars(path)
    if path.startswith("/"):
        return path
    else:
        return os.path.join(get_output_dir(), path)


def get_hash(input_string):
    return hashlib.sha256(input_string.encode("utf-8")).hexdigest()


@singleton
def get_logger():
    return logging.getLogger("pippin")


def mkdirs(path):
    # Do this layer by layer so we can chown correctly
    if not os.path.exists(path):
        parent = os.path.dirname(path)
        mkdirs(parent)
        os.makedirs(path, exist_ok=True, mode=0o7701)
        chown_dir(path)


def copytree(src, dst, symlinks=False, ignore=None):
    lst = os.listdir(src)
    if ignore:
        excl = ignore(src, lst)
        lst = [x for x in lst if x not in excl]
    for item in lst:
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if symlinks and os.path.islink(s):
            if os.path.lexists(d):
                os.remove(d)
                os.symlink(os.readlink(s), d)
                try:
                    st = os.lstat(s)
                    mode = stat.S_IMODE(st.st_mode)
                    os.lchmod(d, mode)
                except:
                    pass  # lchmod not available
        elif os.path.isdir(s):
            copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)


def chown_file(path):
    import grp

    global_config = get_config()
    logger = get_logger()
    groupinfo = grp.getgrnam(global_config["SNANA"]["group"])
    group_id = groupinfo.gr_gid
    try:
        os.chown(path, -1, group=group_id, follow_symlinks=False)
    except Exception:
        logger.debug(f"Did not chown {path}")


def chown_dir(directory):
    import grp

    global_config = get_config()
    logger = get_logger()
    groupinfo = grp.getgrnam(global_config["SNANA"]["group"])
    group_id = groupinfo.gr_gid
    try:
        shutil.chown(directory, group=global_config["SNANA"]["group"])
        os.chmod(directory, 0o770)
    except Exception as e:
        logger.exception(f"Chown error: {directory}")
        return
    for root, dirs, files in os.walk(directory):
        for d in dirs:
            if not os.path.islink(os.path.join(root, d)):
                try:
                    os.chown(os.path.join(root, d), -1, group_id, follow_symlinks=False)
                    os.chmod(os.path.join(root, d), 0o770)
                except Exception as e:
                    logger.warning(f"Chown error: {os.path.join(root, d)}")
        for f in files:
            if not os.path.islink(os.path.join(root, f)):
                try:
                    os.chown(os.path.join(root, f), -1, group_id, follow_symlinks=False)
                    os.chmod(os.path.join(root, f), 0o660)
                except Exception as e:
                    logger.warning(f"Chown error: {os.path.join(root, f)}")


def ensure_list(a):
    if isinstance(a, list):
        return a
    return [a]


if __name__ == "__main__":
    c = get_config()
    print(c.sections())
    print(c.get("SNANA", "sim_dir"))
    print(c["OUTPUT"]["ping_frequency"])
