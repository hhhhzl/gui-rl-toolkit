try:
    import wandb
except:
    pass
import os
import os.path as osp
import sys
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from rlf.exp_mgr import config_mgr
from rlf.rl.utils import CacheHelper


def extract_query_key(k):
    if k.startswith("ALL_"):
        return k.split("ALL_")[1]
    return k


def query(
    select_fields: List[str],
    filter_fields: Dict[str, str],
    cfg="./config.yaml",
    verbose=True,
    limit=None,
    use_cached=False,
    reduce_op: Optional[Callable[[List], float]] = None,
):
    """
    :param select_fields: The list of data to retrieve. If a field starts with
        "ALL_", then all the entries for this name from W&B are fetched. This gets
        the ENTIRE history.
    :param filter_fields: Key is the filter type (like group or tag) and value
        is the filter value (like the name of the group or tag to match)
    :param reduce_op: `np.mean` would take the average of the results.
    """
    config_mgr.init(cfg)

    wb_proj_name = config_mgr.get_prop("proj_name")
    wb_entity = config_mgr.get_prop("wb_entity")

    lookup = f"{select_fields}_{filter_fields}"
    cache = CacheHelper("wb_queries", lookup)

    if use_cached and cache.exists():
        return cache.load()

    api = wandb.Api()

    query_dict = {}

    for f, v in filter_fields.items():
        if f == "group":
            query_dict["group"] = v
        elif f == "tag":
            query_dict["tags"] = v
        else:
            raise ValueError(f"Filter {f}: {v} not supported")

    def log(s):
        if verbose:
            print(s)

    log("Querying with")
    log(query_dict)

    runs = api.runs(f"{wb_entity}/{wb_proj_name}", query_dict)
    log(f"Returned {len(runs)} runs")

    base_data_dir = config_mgr.get_prop("base_data_dir")
    ret_data = []
    for run in runs:
        dat = {}
        for f in select_fields:
            if f == "last_model":
                env_name = run.config["env_name"]
                model_path = osp.join(base_data_dir, "checkpoints", env_name, run.name)
                if not osp.exists(model_path):
                    raise ValueError(f"Could not locate model path {model_path}")
                model_idxs = [
                    int(model_f.split("_")[1].split(".pt")[0])
                    for model_f in os.listdir(model_path)
                    if model_f.startswith("model_")
                ]
                max_idx = max(model_idxs)
                final_model_f = osp.join(model_path, f"model_{max_idx}.pt")
                v = final_model_f
            elif f == "final_train_success":
                # Will by default get the most recent train success metric, if
                # none exists then will get the most recent eval success metric
                # (useful for methods that are eval only)
                succ_keys = [
                    k
                    for k in list(run.summary.keys())
                    if isinstance(k, str)
                    and "success" in k
                    and "std" not in k
                    and "max" not in k
                    and "min" not in k
                ]
                train_succ_keys = [
                    k for k in succ_keys if "eval_final" in k or "eval_train" in k
                ]
                if len(train_succ_keys) > 0:
                    use_k = train_succ_keys[0]
                elif len(succ_keys) > 0:
                    use_k = succ_keys[0]
                else:
                    print(
                        "Could not find success key from ",
                        run.summary.keys(),
                        "Possibly due to run failure. Run status",
                        run.state,
                    )
                    return None
                v = run.summary[use_k]
            elif f == "status":
                v = run.state
            elif f.startswith("config."):
                v = run.config[f.split("config.")[0]]
            else:
                if f.startswith("ALL_"):
                    fetch_field = extract_query_key(f)
                    df = run.history(samples=15000)
                    if fetch_field not in df.columns:
                        raise ValueError(
                            f"Could not find {fetch_field} in {df.columns} for query {filter_fields}"
                        )
                    v = df[["_step", fetch_field]]
                else:
                    v = run.summary[f]
            dat[f] = v
        ret_data.append(dat)
        if limit is not None and len(ret_data) >= limit:
            break

    cache.save(ret_data)
    if reduce_op is not None:
        reduce_data = defaultdict(list)
        for p in ret_data:
            for k, v in p.items():
                reduce_data[k].append(v)
        ret_data = {k: reduce_op(v) for k, v in reduce_data.items()}

    log(f"Got data {ret_data}")
    return ret_data


def query_s(query_str, verbose=True):
    select_s, filter_s = query_str.split(" WHERE ")
    select_fields = select_s.replace(" ", "").split(",")

    parts = filter_s.split(" LIMIT ")
    filter_s = parts[0]

    limit = None
    if len(parts) > 1:
        limit = int(parts[1])

    filter_fields = filter_s.replace(" ", "").split(",")
    filter_fields = [s.split("=") for s in filter_fields]
    filter_fields = {k: v for k, v in filter_fields}

    return query(select_fields, filter_fields, verbose=verbose, limit=limit)


if __name__ == "__main__":
    query_str = " ".join(sys.argv[1:])
    query_s(query_str)
