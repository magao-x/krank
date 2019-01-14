#!/usr/bin/env python3
'''
Krank KLIPs high contrast imaging data in a distributed fashion
'''
import sys
import os
import socket
from pathlib import Path
import argparse
import json
import asyncio
import datetime
import itertools
import pytest
import subprocess
import shlex

DEFAULT_INTERFACE = '::'  # IPv6, all interfaces
DEFAULT_PORT = 9876

WAITING, CLAIMED, COMPLETED, FAILED = TASK_STATES = (
    'WAITING', 'CLAIMED', 'COMPLETED', 'FAILED'
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
    if '__isoformat__' in json_dict:
        return datetime.datetime.fromisoformat(json_dict['datetime'])
    return json_dict

def custom_json_encodings(obj):
    if isinstance(obj, datetime.datetime):
        return {
           '__isoformat__': 1,
           'datetime': obj.isoformat(),
        }
    else:
        raise TypeError("Cannot encode {} to JSON".format(repr(obj)))

def hostname_to_ips(hostname):
    '''Get IP address(es) for a hostname using `socket.getaddrinfo`'''
    # based on https://stackoverflow.com/a/44397805
    some_port = 0
    ips = list(map(lambda x: x[4][0], socket.getaddrinfo(hostname, some_port, type=socket.SOCK_STREAM)))
    assert len(ips), 'No IPs from getaddrinfo!'
    return ips

def hostname_to_ip(hostname, prefer='ipv6'):
    '''Resolve a hostname to an IP, optionally preferring either `'ipv4'`
    or `'ipv6'` with the ``prefer=`` argument.
    '''
    ips = hostname_to_ips(hostname)
    if len(ips) == 1:
        ip = ips[0]
    else:
        ipv6_ips = [x for x in ips if ':' in x]
        ipv4_ips = [x for x in ips if '.' in x]
        assert max(len(ipv4_ips), len(ipv6_ips)) > 0, 'Neither IPv4 nor IPv6 IPs were detected'
        if prefer.lower() == 'ipv4':
            ip = ipv4_ips[0] if ipv4_ips else ipv6_ips[0]
        elif prefer.lower() == 'ipv6':
            ip = ipv6_ips[0] if ipv6_ips else ipv4_ips[0]
    return ip

def test_hostname_to_ip():
    assert hostname_to_ip('localhost', prefer='ipv4') == '127.0.0.1'
    assert hostname_to_ip('localhost', prefer='ipv6') == '::1'
    assert hostname_to_ip('localhost') == '::1'

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
            with open(persistence_file_path, 'r') as handle:
                ledger.store = json.load(handle, object_hook=custom_json_decodings)
            if not set(ledger.store.keys()) == set(TASK_STATES):
                raise RuntimeError(f"JSON from {persistence_file_path} "
                                   "is not a valid state file")
        else:
            await ledger.save()
        return ledger
    async def save(self):
        with open(self.persistence_file_path, 'w') as handle:
            json.dump(self.store, handle, default=custom_json_encodings)
    async def add_command(self, command):
        task = {
            'command': command,
            'created': datetime.datetime.now(),
            'changed': datetime.datetime.now(),
            'attempts': 0,
        }
        self.store[WAITING].append(task)
        await self.save()
        return task
    async def add_many(self, commands_iterable):
        now = datetime.datetime.now()
        tasks = [
            {
                'command': command,
                'created': now,
                'changed': now,
                'attempts': 0,
            } for command in commands_iterable
        ]
        self.store[WAITING].extend(tasks)
        return tasks
    async def get_waiting_task(self):
        task = self.store[WAITING].pop(0)
        task['attempts'] += 1
        task['changed'] = datetime.datetime.now()
        self.store[CLAIMED].append(task)
        await self.save()
        return task
    async def complete_task(self, task):
        print('completed {}'.format(task))
        n_claimed = len(self.store[CLAIMED])
        idx = self.store[CLAIMED].index(task)
        assert idx != -1
        task = self.store[CLAIMED].pop(idx)
        assert len(self.store[CLAIMED]) < n_claimed
        print('popped', task)
        task['changed'] = datetime.datetime.now()
        self.store[COMPLETED].append(task)
        await self.save()
        return task
    async def unclaim_task(self, task):
        idx = self.store[CLAIMED].index(task)
        task = self.store[CLAIMED].pop(idx)
        if task['attempts'] < MAX_ATTEMPTS:
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

@pytest.mark.asyncio
async def test_ledger_deserialization():
    import tempfile
    with tempfile.TemporaryDirectory() as loc:
        # Create new, empty ledger
        ledger_path = Path(loc) / 'ledger.json'
        ledger = await Ledger.from_disk(ledger_path)
        with open(ledger_path, 'r') as f:
            ledger_contents = json.load(f, object_hook=custom_json_decodings)
            assert ledger_contents == {
                WAITING: [],
                CLAIMED: [],
                COMPLETED: [],
                FAILED: [],
            }
        # Place task in the queue (and implicitly save to disk)
        cmd = 'echo "foo\'s bar"'
        task_spec = await ledger.add_command(cmd)
        # Load JSON from disk directly and verify contents deserialize
        # to the same task_spec
        with open(ledger_path, 'r') as f:
            ledger_contents = json.load(f, object_hook=custom_json_decodings)
            assert ledger_contents[WAITING][0] == task_spec
        # Load Ledger through API and verify contents match task_spec
        updated_ledger = await Ledger.from_disk(ledger_path)
        assert updated_ledger.waiting[0] == task_spec

flatten = lambda z: [x for y in z for x in y]
flatten.__doc__ = 'Flattens a sequence of sequences into a single list'

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

def test_permutator():
    p = Permutator({'--foo': ['a', 'b'], '--bar': ['c'], '--baz': ['d', 'e']})
    option_sets = [
        ['--foo', 'a', '--bar', 'c', '--baz', 'd'],
        ['--foo', 'a', '--bar', 'c', '--baz', 'e'],
        ['--foo', 'b', '--bar', 'c', '--baz', 'd'],
        ['--foo', 'b', '--bar', 'c', '--baz', 'e']
    ]
    assert list(p) == option_sets

class Koordinator:
    def __init__(self, ledger, host, port):
        self.ledger = ledger
        self.host = host
        self.port = port
        self.server = None
        self._state = STARTING
    @property
    def running(self):
        return self.server is not None and self.server.is_serving()
    async def stop(self):
        self._state = STOPPING
        print('stopping in {}'.format(SHUTDOWN_WAIT_SEC))
        # give connecting clients a chance to hear the news:
        await asyncio.sleep(SHUTDOWN_WAIT_SEC)
        # shut down cleanly:
        self.server.close()
        print('closed...')
        self._state = STOPPED
    async def dispatch(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"Dispatching a Koordinator coroutine to talk with {addr!r}")
        if len(self.ledger.waiting):
            next_task = await self.ledger.get_waiting_task()
        else:
            # n.b. just because we're out of task specs from the generator
            # doesn't mean we're actually ready to quit. if a task that's
            # been claimed fails and needs to be retried, it will move
            # back to WAITING
            next_task = None

        # push over the spec as json
        if next_task is not None:
            message = {
                'type': MSG_TASK_START,
                'command': next_task['command'],
            }
        elif len(self.ledger.claimed) != 0:
            print(self.ledger.claimed)
            # claimed tasks may still fail and need to be retried
            # so don't start telling klients to exit until
            # there is nothing left to do
            message = {
                'type': MSG_CHECK_LATER
            }
        else:
            # every task is either completed or failed, nothing left to do
            # so we tell klients to exit
            message = {
                'type': MSG_SHUTDOWN,
            }
        try:
            message_json = json.dumps(message)
            writer.write(message_json.encode() + b'\n')
            await writer.drain()
            print('wrote {}'.format(message_json))
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
        if response['type'] == MSG_TASK_SUCCESS:
            await self.ledger.complete_task(next_task)
        elif response['type'] == MSG_TASK_FAILED:
            await self.ledger.unclaim_task(next_task)
        elif response['type'] == MSG_CHECK_LATER:
            print('klient will check back later')
        elif response['type'] == MSG_SHUTDOWN:
            print('klient acknowledged shutdown')
        else:
            raise RuntimeError("Unknown message type from klient")
        if next_task is None and len(self.ledger.claimed) == 0:
            # If we are out of tasks, and all running tasks have completed
            # or failed, it's safe to shut down
            await self.stop()
    async def run(self):
        self.server = await asyncio.start_server(self.dispatch, host=self.host, port=self.port)
        addr = self.server.sockets[0].getsockname()
        print(f'Serving on {addr}')
        self._state = RUNNING
        async with self.server:
            await self.server.wait_closed()
        print('wait_closed finished')

class Klient:
    def __init__(self, koordinator_host, koordinator_port, dummy=False):
        self.status = STARTING
        self.last_communication = datetime.datetime.now()
        self.koordinator_host, self.koordinator_port = koordinator_host, koordinator_port
        # Can only use one of IPv4 *or* IPv6, and passing
        # hostnames can give you multiple IPs...
        # See https://bugs.python.org/issue29980
        self.koordinator_ip = hostname_to_ip(self.koordinator_host)
        self.dummy = dummy
    def stop(self):
        self.status = STOPPING
    def invoke(self, command):
        if self.dummy:
            print('Got request to execute:\n\n{}\n\n'.format(command))
            return {'success': True, 'output': '<dummy mode: nothing executed>'}
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
        return {'success': success, 'output': output}
    async def run(self):
        self.status = RUNNING
        while self.status not in (STOPPING, STOPPED):
            # connect to Koordinator
            try:
                print('about to connect to {}:{}'.format(
                    self.koordinator_ip,
                    self.koordinator_port
                ))
                reader, writer = await asyncio.open_connection(
                    self.koordinator_ip,
                    self.koordinator_port
                )
                print('connected')
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
                    print("Retrying in {} seconds".format(RECONNECTION_WAIT_SEC))
                    await asyncio.sleep(RECONNECTION_WAIT_SEC)
                    continue
            # when successful, update self.last_communication
            self.last_communication = datetime.datetime.now()
            # get a task spec and deserialize
            message_text = await reader.readline()
            print('got message text {}'.format(message_text))
            message = json.loads(
                message_text,
                object_hook=custom_json_decodings
            )
            if message['type'] == MSG_SHUTDOWN:
                response = {
                    'type': MSG_SHUTDOWN,
                }
                self.stop()
            elif message['type'] == MSG_CHECK_LATER:
                response = {
                    'type': MSG_CHECK_LATER
                }
            elif message['type'] == MSG_TASK_START:
                result = self.invoke(message['command'])
                if result['success']:
                    response = {
                        'type': MSG_TASK_SUCCESS,
                        'output': result['output'],
                    }
                else:
                    response = {
                        'type': MSG_TASK_FAILED,
                        'output': result['output'],
                    }
            response_text = json.dumps(response).encode()
            writer.writelines([response_text,])
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            if message['type'] == MSG_CHECK_LATER:
                await asyncio.sleep(RECONNECTION_WAIT_SEC)
        if self.status == STOPPING:
            self.status = STOPPED

async def start_koordinator(args):
    print('koordinator', args)
    ledger = await Ledger.from_disk(args.ledger)
    tasks_iterable = Permutator({'--foo': ['a', 'b'], '--bar': ['c'], '--baz': ['d', 'e']})
    await ledger.add_many(tasks_iterable)
    app = Koordinator(ledger, args.interface, args.port)
    await app.run()
    return 0

async def start_klient(args):
    print('klient', args)
    klient = Klient(args.koordinator_host, args.port, dummy=args.dummy)
    await klient.run()
    return 0

@pytest.mark.asyncio
async def test_klient_koordinator():
    async def test_klient():
        pass
    async def test_koordinator():
        pass
    asyncio.gather(
        test_klient(),
        test_koordinator(),
    )

def main():
    import pathlib
    cwd = pathlib.Path(os.getcwd())
    default_ledger_path = cwd / 'ledger.json'
    parser = argparse.ArgumentParser(description=__doc__)

    subparsers = parser.add_subparsers(dest='command_name')
    koordinator_parser = subparsers.add_parser('koordinator')
    koordinator_parser.set_defaults(func=start_koordinator)
    koordinator_parser.add_argument(
        '-l', '--ledger',
        required=False, default=default_ledger_path,
        help="Filesystem path to a JSON file containing job states"
    )
    koordinator_parser.add_argument(
        '-i', '--interface',
        required=False, default=DEFAULT_INTERFACE,
        help="Interface (IP) on which to listen for klient connections"
    )
    koordinator_parser.add_argument(
        '-p', '--port',
        required=False, type=int, default=DEFAULT_PORT,
        help="Port the koordinator listens on"
    )

    klient_parser = subparsers.add_parser('klient')
    klient_parser.set_defaults(func=start_klient)
    klient_parser.add_argument(
        'koordinator_host',
        help="Hostname or IP of a host running Koordinator"
    )
    klient_parser.add_argument(
        '-p', '--port',
        type=int, default=DEFAULT_PORT,
        help="Koordinator host port"
    )
    klient_parser.add_argument(
        '-d', '--dummy',
        action='store_true',
        help="Print commands that would be executed without executing them"
    )

    args = parser.parse_args()
    if args.command_name is None:
        parser.parse_args(['-h'])
    else:
        return asyncio.run(args.func(args))

if __name__ == "__main__":
    sys.exit(main())