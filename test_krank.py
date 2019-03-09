import asyncio
import json
from pathlib import Path
import pytest
import krank


def test_hostname_to_ip():
    assert krank.hostname_to_ip('localhost', prefer='ipv4') == '127.0.0.1'
    assert krank.hostname_to_ip('localhost', prefer='ipv6') == '::1'
    assert krank.hostname_to_ip('localhost') == '::1'

@pytest.mark.asyncio
async def test_ledger_deserialization():
    import tempfile
    with tempfile.TemporaryDirectory() as loc:
        # Create new, empty ledger
        ledger_path = Path(loc) / 'ledger.json'
        ledger = await krank.Ledger.from_disk(ledger_path)
        with open(ledger_path, 'r') as f:
            ledger_contents = json.load(f, object_hook=krank.custom_json_decodings)
            assert ledger_contents == {
                krank.WAITING: [],
                krank.CLAIMED: [],
                krank.COMPLETED: [],
                krank.FAILED: [],
            }
        # Place task in the queue (and implicitly save to disk)
        cmd = 'echo "foo\'s bar"'
        task_spec = await ledger.add_command(cmd)
        # Load JSON from disk directly and verify contents deserialize
        # to the same task_spec
        with open(ledger_path, 'r') as f:
            ledger_contents = json.load(f, object_hook=krank.custom_json_decodings)
            assert ledger_contents[krank.WAITING][0] == task_spec
        # Load Ledger through API and verify contents match task_spec
        updated_ledger = await krank.Ledger.from_disk(ledger_path)
        assert updated_ledger.waiting[0] == task_spec

def test_permutator():
    p = krank.Permutator({"--foo": ["a", "b"], "--bar": ["c"], "--baz": ["d", "e"]})
    option_sets = [
        ['--foo', 'a', '--bar', 'c', '--baz', 'd'],
        ['--foo', 'a', '--bar', 'c', '--baz', 'e'],
        ['--foo', 'b', '--bar', 'c', '--baz', 'd'],
        ['--foo', 'b', '--bar', 'c', '--baz', 'e']
    ]
    assert list(p) == option_sets


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


def test_write_read_connection_info():
    from io import StringIO
    fake_file = StringIO()
    krank.write_connection_info(fake_file, krank.DEFAULT_HOSTNAME, krank.DEFAULT_PORT)
    fake_file.seek(0)
    loaded_host, loaded_port = krank.read_connection_info(fake_file)
    assert loaded_host == krank.DEFAULT_HOSTNAME
    assert loaded_port == krank.DEFAULT_PORT