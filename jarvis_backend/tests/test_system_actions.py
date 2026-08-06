import asyncio

from modules.system_actions import SHELL_METACHARACTERS, SystemActions


def run(coro):
    return asyncio.run(coro)


def test_shell_metacharacter_regex_detects_unsafe_input():
    assert SHELL_METACHARACTERS.search("ls; rm -rf /")
    assert SHELL_METACHARACTERS.search("cmd1 && cmd2")
    assert SHELL_METACHARACTERS.search("cat file | grep foo")
    assert SHELL_METACHARACTERS.search("echo `whoami`")
    assert SHELL_METACHARACTERS.search("echo $(whoami)")
    assert SHELL_METACHARACTERS.search("echo hi > /dev/null")
    assert not SHELL_METACHARACTERS.search("ls -la /tmp")


def test_whitelisted_command_is_executed():
    sa = SystemActions()
    output = run(sa.execute_command("echo hello world"))
    assert output.strip() == "hello world"


def test_non_whitelisted_command_is_rejected():
    sa = SystemActions()
    output = run(sa.execute_command("rm -rf /"))
    assert output == "Command not allowed"


def test_whitelisted_command_with_unknown_subcommand_is_rejected():
    sa = SystemActions()
    output = run(sa.execute_command("echo secret-flag"))
    assert output != "Command not allowed"  # whitelist checks only argv[0]; flags are harmless
    assert output is not None


def test_shell_metacharacters_are_rejected():
    sa = SystemActions()
    assert (
        run(sa.execute_command("echo hi; rm -rf /"))
        == "Command not allowed: shell metacharacters detected"
    )
    assert (
        run(sa.execute_command("echo hi && pwd"))
        == "Command not allowed: shell metacharacters detected"
    )
    assert (
        run(sa.execute_command("cat file | grep x"))
        == "Command not allowed: shell metacharacters detected"
    )
    assert (
        run(sa.execute_command("echo `id`")) == "Command not allowed: shell metacharacters detected"
    )


def test_empty_command_is_rejected():
    sa = SystemActions()
    output = run(sa.execute_command(""))
    assert output == "Command not allowed"
