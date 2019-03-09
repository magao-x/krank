#!/usr/bin/env python3
"""
Krank KLIPs high contrast imaging data in a distributed fashion
"""
import sys
import os
import socket
from pathlib import Path
import argparse
import json
import asyncio
import datetime
import itertools
import subprocess

DEFAULT_INTERFACE = "::"  # IPv6, all interfaces
DEFAULT_PORT = 9876

DEFAULT_CONNECTION_INFO_FILENAME = "koordinator_connection_info.json"
DEFAULT_LEDGER_FILENAME = "ledger.json"

WAITING, CLAIMED, COMPLETED, FAILED = TASK_STATES = (
    "WAITING", "CLAIMED", "COMPLETED", "FAILED"
)

STARTING, RUNNING, STOPPING, STOPPED = 1, 2, 3, 4

(
    MSG_TASK_START,
    MSG_TASK_SUCCESS,
    MSG_TASK_FAILED,
    MSG_SHUTDOWN,
    MSG_CHECK_LATER,
) = range(5)

MAX_ATTEMPTS = 5
RECONNECTION_WAIT_SEC = 5
CHECK_RUNNING_TASKS_SEC = 5
MAX_COMMUNICATION_WAIT_SEC = 10
MAX_TASK_EXECUTION_SEC = 60 * 60
SHUTDOWN_WAIT_SEC = ABANDONED_KLIENT_TIMEOUT_SEC = 1


def custom_json_decodings(json_dict):
    if "__isoformat__" in json_dict:
        return datetime.datetime.fromisoformat(json_dict["datetime"])
    return json_dict


def custom_json_encodings(obj):
    if isinstance(obj, datetime.datetime):
        return {
            "__isoformat__": 1,
            "datetime": obj.isoformat(),
        }
    else:
        raise TypeError("Cannot encode {} to JSON".format(repr(obj)))


def hostname_to_ips(hostname):
    """Get IP address(es) for a hostname using `socket.getaddrinfo`"""
    # based on https://stackoverflow.com/a/44397805
    some_port = 0
    ips = list(map(lambda x: x[4][0], socket.getaddrinfo(
        hostname, some_port, type=socket.SOCK_STREAM)))
    assert len(ips), "No IPs from getaddrinfo!"
    return ips


def hostname_to_ip(hostname, prefer="ipv6"):
    """Resolve a hostname to an IP, optionally preferring either `"ipv4"`
    or `"ipv6"` with the ``prefer=`` argument.
    """
    ips = hostname_to_ips(hostname)
    if len(ips) == 1:
        ip = ips[0]
    else:
        ipv6_ips = [x for x in ips if ":" in x]
        ipv4_ips = [x for x in ips if "." in x]
        assert max(len(ipv4_ips), len(ipv6_ips)
                   ) > 0, "Neither IPv4 nor IPv6 IPs were detected"
        if prefer.lower() == "ipv4":
            ip = ipv4_ips[0] if ipv4_ips else ipv6_ips[0]
        elif prefer.lower() == "ipv6":
            ip = ipv6_ips[0] if ipv6_ips else ipv4_ips[0]
    return ip


class Ledger:
    def __init__(self, file_path):
        self.persistence_file_path = Path(file_path)
        self.store = {
            WAITING: [],
            CLAIMED: [],
            COMPLETED: [],
            FAILED: [],
        }

    @classmethod
    async def from_disk(cls, persistence_file_path):
        ledger = cls(persistence_file_path)
        if os.path.exists(persistence_file_path):
            with open(persistence_file_path, "r") as handle:
                ledger.store = json.load(
                    handle, object_hook=custom_json_decodings)
            if not set(ledger.store.keys()) == set(TASK_STATES):
                raise RuntimeError(f"JSON from {persistence_file_path} "
                                   "is not a valid state file")
        else:
            await ledger.save()
        return ledger

    async def save(self):
        with open(self.persistence_file_path, "w") as handle:
            json.dump(self.store, handle, default=custom_json_encodings)

    async def add_command(self, command):
        task = {
            "command": command,
            "created": datetime.datetime.now(),
            "changed": datetime.datetime.now(),
            "attempts": 0,
        }
        self.store[WAITING].append(task)
        await self.save()
        return task

    async def add_many(self, command, options_iterable):
        now = datetime.datetime.now()
        tasks = [
            {
                "command": command + " " + " ".join(options),
                "created": now,
                "changed": now,
                "attempts": 0,
            } for options in options_iterable
        ]
        self.store[WAITING].extend(tasks)
        return tasks

    async def get_waiting_task(self):
        task = self.store[WAITING].pop(0)
        task["attempts"] += 1
        task["changed"] = datetime.datetime.now()
        self.store[CLAIMED].append(task)
        await self.save()
        return task

    async def complete_task(self, task):
        print("completed {}".format(task))
        n_claimed = len(self.store[CLAIMED])
        idx = self.store[CLAIMED].index(task)
        assert idx != -1
        task = self.store[CLAIMED].pop(idx)
        assert len(self.store[CLAIMED]) < n_claimed
        print("popped", task)
        task["changed"] = datetime.datetime.now()
        self.store[COMPLETED].append(task)
        await self.save()
        return task

    async def unclaim_task(self, task):
        idx = self.store[CLAIMED].index(task)
        task = self.store[CLAIMED].pop(idx)
        if task["attempts"] < MAX_ATTEMPTS:
            self.store[WAITING].append(task)
        else:
            self.store[FAILED].append(task)
        await self.save()
        return task

    @property
    def waiting(self):
        return self.store[WAITING]

    @property
    def claimed(self):
        return self.store[CLAIMED]

    @property
    def completed(self):
        return self.store[COMPLETED]

    @property
    def failed(self):
        return self.store[FAILED]


def flatten(z):
    """Flattens a sequence of sequences into a single list"""
    return [x for y in z for x in y]


class Permutator:
    def __init__(self, options):
        self.options = options

    def _generate_options(self):
        option_names = list(self.options.keys())
        option_values = [self.options[name] for name in option_names]
        for option_combination in itertools.product(*option_values):
            yield flatten(zip(option_names, option_combination))

    def __iter__(self):
        return self._generate_options()


class Koordinator:
    def __init__(self, ledger, hostname, port, connection_info_filename):
        self.ledger = ledger
        self._state = STARTING
        self.connection_info_path = Path(connection_info_filename)
        if self.connection_info_path.exists():
            raise RuntimeError(
                f"{self.connection_info_path!r} already exists! Ensure Koordinator is "
                "not already running and delete it."
            )
        self.hostname = socket.getfqdn() if hostname is None else hostname
        self.port = port
        # Initialized after starting asyncio server in self.run()
        self.server = None
        self.address = None

    @property
    def running(self):
        return self.server is not None and self.server.is_serving()

    async def stop(self):
        self._state = STOPPING
        print("stopping in {}".format(SHUTDOWN_WAIT_SEC))
        # give connecting clients a chance to hear the news:
        await asyncio.sleep(SHUTDOWN_WAIT_SEC)
        # shut down cleanly:
        self.server.close()
        print("closed...")
        self._state = STOPPED

    async def dispatch(self, reader, writer):
        addr = writer.get_extra_info("peername")
        print(f"Dispatching a Koordinator coroutine to talk with {addr!r}")
        if len(self.ledger.waiting):
            next_task = await self.ledger.get_waiting_task()
        else:
            # n.b. just because we"re out of task specs from the generator
            # doesn"t mean we"re actually ready to quit. if a task that"s
            # been claimed fails and needs to be retried, it will move
            # back to WAITING
            next_task = None

        # push over the spec as json
        if next_task is not None:
            message = {
                "type": MSG_TASK_START,
                "command": next_task["command"],
            }
        elif len(self.ledger.claimed) != 0:
            print(self.ledger.claimed)
            # claimed tasks may still fail and need to be retried
            # so don"t start telling klients to exit until
            # there is nothing left to do
            message = {
                "type": MSG_CHECK_LATER
            }
        else:
            # every task is either completed or failed, nothing left to do
            # so we tell klients to exit
            message = {
                "type": MSG_SHUTDOWN,
            }
        try:
            message_json = json.dumps(message)
            writer.write(message_json.encode() + b"\n")
            await writer.drain()
            print("wrote {}".format(message_json))
            response_text = await asyncio.wait_for(
                reader.readline(),
                MAX_TASK_EXECUTION_SEC
            )
            response = json.loads(
                response_text,
                object_hook=custom_json_decodings
            )
        except (asyncio.TimeoutError, json.JSONDecodeError) as e:
            if next_task is not None:
                await self.ledger.unclaim_task(next_task)
                print("Failed to run {}".format(next_task))
            print(e)
            return
        finally:
            writer.close()
            await writer.wait_closed()
        if response["type"] == MSG_TASK_SUCCESS:
            await self.ledger.complete_task(next_task)
        elif response["type"] == MSG_TASK_FAILED:
            await self.ledger.unclaim_task(next_task)
        elif response["type"] == MSG_CHECK_LATER:
            print("klient will check back later")
        elif response["type"] == MSG_SHUTDOWN:
            print("klient acknowledged shutdown")
        else:
            raise RuntimeError("Unknown message type from klient")
        if next_task is None and len(self.ledger.claimed) == 0:
            # If we are out of tasks, and all running tasks have completed
            # or failed, it"s safe to shut down
            await self.stop()

    async def run(self):
        self.server = await asyncio.start_server(
            self.dispatch,
            host=DEFAULT_INTERFACE,
            port=self.port
        )
        self.address = self.server.sockets[0].getsockname()
        # n.b. if port was 0, this updates it with the actual assigned port:
        self.port = self.address[1]

        print(
            f"Serving on {self.address[0]}:{self.port}, advertising as {self.hostname}:{self.port}")
        with self.connection_info_path.open('w') as file_handle:
            write_connection_info(file_handle, self.hostname, self.port)
        self._state = RUNNING
        async with self.server:
            await self.server.wait_closed()
        print("wait_closed finished")


class Klient:
    def __init__(self, koordinator_host, koordinator_port, dummy=False):
        self.status = STARTING
        self.last_communication = datetime.datetime.now()
        self.koordinator_host, self.koordinator_port = koordinator_host, koordinator_port
        print(f"Configured with koordinator {connection_info}")
        # Can only use one of IPv4 *or* IPv6, and passing
        # hostnames can give you multiple IPs...
        # See https://bugs.python.org/issue29980
        self.koordinator_ip = hostname_to_ip(self.koordinator_host)
        self.dummy = dummy

    def stop(self):
        self.status = STOPPING

    def invoke(self, command):
        if self.dummy:
            print("Got request to execute:\n\n{}\n\n".format(command))
            return {"success": True, "output": "<dummy mode: nothing executed>"}
        try:
            output = subprocess.check_output(
                command,
                stderr=subprocess.STDOUT,
                shell=True,
            )
            success = True
        except subprocess.CalledProcessError as exception:
            success = False
            output = exception.output
        output = output.decode('utf-8')
        return {"success": success, "output": output}

    async def run(self):
        self.status = RUNNING
        while self.status not in (STOPPING, STOPPED):
            # connect to Koordinator
            try:
                print("about to connect to {}:{}".format(
                    self.koordinator_ip,
                    self.koordinator_port
                ))
                reader, writer = await asyncio.open_connection(
                    self.koordinator_ip,
                    self.koordinator_port
                )
                print("connected")
            except (ConnectionRefusedError, TimeoutError) as e:
                # if failed,
                time_since = datetime.datetime.now() - self.last_communication
                if time_since.seconds > ABANDONED_KLIENT_TIMEOUT_SEC:
                    # ... and last_communication was too long ago:
                    self.stop()
                    continue
                else:
                    print("Couldn't connect: {}".format(e))
                    # ... and last_communication was recent:
                    print("Retrying in {} seconds".format(
                        RECONNECTION_WAIT_SEC))
                    await asyncio.sleep(RECONNECTION_WAIT_SEC)
                    continue
            # when successful, update self.last_communication
            self.last_communication = datetime.datetime.now()
            # get a task spec and deserialize
            message_text = await reader.readline()
            print("got message text {}".format(message_text))
            message = json.loads(
                message_text,
                object_hook=custom_json_decodings
            )
            if message["type"] == MSG_SHUTDOWN:
                response = {
                    "type": MSG_SHUTDOWN,
                }
                self.stop()
            elif message["type"] == MSG_CHECK_LATER:
                response = {
                    "type": MSG_CHECK_LATER
                }
            elif message["type"] == MSG_TASK_START:
                result = self.invoke(message["command"])
                if result["success"]:
                    response = {
                        "type": MSG_TASK_SUCCESS,
                        "output": result["output"],
                    }
                else:
                    response = {
                        "type": MSG_TASK_FAILED,
                        "output": result["output"],
                    }
            response_text = json.dumps(response).encode()
            writer.writelines([response_text, ])
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            if message["type"] == MSG_CHECK_LATER:
                await asyncio.sleep(RECONNECTION_WAIT_SEC)
        if self.status == STOPPING:
            self.status = STOPPED


def write_connection_info(file_handle, host, port):
    json.dump({"host": host, "port": port}, file_handle)
    return host, port


def read_connection_info(file_handle):
    connection_info = json.load(file_handle)
    if not 'host' in connection_info or not 'port' in connection_info:
        raise RuntimeError(
            "Malformed connection info, deserialized to {}".format(
                repr(connection_info))
        )
    return connection_info['host'], connection_info['port']


async def start_koordinator(args):
    print("koordinator", args)
    ledger = await Ledger.from_disk(args.ledger)
    with open(args.options_json_file, "r") as f:
        options_dict = json.load(f)
    tasks_iterable = Permutator(options_dict)
    await ledger.add_many(" ".join(args.command_to_run), tasks_iterable)
    app = Koordinator(ledger, args.hostname, args.port, args.connection_info)
    await app.run()
    return 0


async def start_klient(args):
    print("klient", args)
    if args.hostname is not None:
        hostname, port = args.hostname, args.port
    else:
        connection_info_path = Path(args.connection_info)
        with connection_info_path.open('r') as file_handle:
            hostname, port = read_connection_info(file_handle)
    klient = Klient(hostname, port, dummy=args.dummy)
    await klient.run()
    return 0


def main():
    import pathlib
    cwd = pathlib.Path(os.getcwd())
    default_ledger_path = cwd / DEFAULT_LEDGER_FILENAME
    default_connection_info_path = cwd / DEFAULT_CONNECTION_INFO_FILENAME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-p", "--port",
        required=False, type=int, default=DEFAULT_PORT,
        help="Port the koordinator listens on "
             "(default: {})".format(DEFAULT_PORT)
    )
    parser.add_argument(
        "-n", "--hostname",
        required=False,
        help="Koordinator hostname (to advertise / connect to), super"
    )
    subparsers = parser.add_subparsers(dest="command_name")
    koordinator_parser = subparsers.add_parser("koordinator")
    koordinator_parser.set_defaults(func=start_koordinator)
    koordinator_parser.add_argument(
        "-l", "--ledger",
        required=False, default=default_ledger_path,
        help="Filesystem path to a JSON file containing job states "
             "(default: ./{})".format(DEFAULT_LEDGER_FILENAME)
    )
    koordinator_parser.add_argument(
        "-c", "--write-connection-details-to",
        metavar="CONNECTION_INFO_PATH",
        dest="connection_info",
        required=False, default=default_connection_info_path,
        help="Filesystem path to write klient connection info to "
             "(default: ./{})".format(DEFAULT_CONNECTION_INFO_FILENAME)
    )
    koordinator_parser.add_argument(
        "command_to_run", nargs="+",
        help="base command and any arguments to which the "
             "permuted arguments are appended"
    )
    koordinator_parser.add_argument(
        "options_json_file",
        help="Filesystem path to a JSON file containing job states "
             "where keys correspond to flags and values are lists "
             "of possible options to supply after the flag on the "
             "command line, cartesian product style"
    )

    klient_parser = subparsers.add_parser("klient")
    klient_parser.set_defaults(func=start_klient)
    klient_parser.add_argument(
        "-c", "--read-connection-details-from",
        metavar="CONNECTION_INFO_PATH",
        dest="connection_info",
        required=False, default=default_connection_info_path,
        help="Filesystem path to read koordinator connection info from "
             "(default: ./{})".format(DEFAULT_CONNECTION_INFO_FILENAME)
    )
    klient_parser.add_argument(
        "-d", "--dummy",
        action="store_true",
        help="Print commands that would be executed without executing them"
    )

    args = parser.parse_args()
    if args.command_name is None:
        parser.parse_args(["-h"])
        return 1
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
