from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

# Firestore and Redis calls spend most of their time waiting on the network,
# so running independent calls at the same time makes a page load much faster.
_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="parallel")


def run_parallel(*tasks: Callable[[], object]) -> list:
    """Runs the functions at the same time and returns their results in the same order.

    profile, products = run_parallel(lambda: load_profile(id), lambda: load_products(id))
    """
    futures = [_pool.submit(task) for task in tasks]
    return [future.result() for future in futures]
