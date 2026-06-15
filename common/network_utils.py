import subprocess
import logging

logger = logging.getLogger(__name__)

def configure_neighbor(
    receiver_ip,
    receiver_mac,
    interface
):
    cmd = [
        "sudo",
        "ip",
        "neigh",
        "replace",
        receiver_ip,
        "lladdr",
        receiver_mac,
        "dev",
        interface,
        "nud",
        "permanent",
    ]

    logger.info(
        f"Mapping {receiver_ip} -> {receiver_mac}"
    )

    subprocess.run(
        cmd,
        check=True
    )