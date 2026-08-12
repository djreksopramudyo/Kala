"""Notify: credential resolution (env-var over config file) tests.

The security goal being tested: on a server the Telegram token should live
only in the environment (a root-owned systemd drop-in), never in
runner_config.json — but an existing laptop setup that only has the config
file must keep working unchanged.
"""


from kala.notify import CHAT_ID_ENV, TOKEN_ENV, resolve_telegram_credentials


def test_env_vars_take_precedence_over_config(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "env-token")
    monkeypatch.setenv(CHAT_ID_ENV, "env-chat")
    token, chat_id = resolve_telegram_credentials(
        {"telegram_token": "cfg-token", "telegram_chat_id": "cfg-chat"})
    assert token == "env-token"
    assert chat_id == "env-chat"


def test_falls_back_to_config_when_env_absent(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(CHAT_ID_ENV, raising=False)
    token, chat_id = resolve_telegram_credentials(
        {"telegram_token": "cfg-token", "telegram_chat_id": "cfg-chat"})
    assert token == "cfg-token"
    assert chat_id == "cfg-chat"


def test_empty_env_does_not_blank_out_working_config(monkeypatch):
    """A stray blank export (KALA_TELEGRAM_TOKEN='') must not override a
    real config value — otherwise a typo in a shell profile silently takes
    the bot offline."""
    monkeypatch.setenv(TOKEN_ENV, "")
    monkeypatch.setenv(CHAT_ID_ENV, "   ")            # whitespace-only too
    token, chat_id = resolve_telegram_credentials(
        {"telegram_token": "cfg-token", "telegram_chat_id": "cfg-chat"})
    assert token == "cfg-token"
    assert chat_id == "cfg-chat"


def test_each_value_resolves_independently(monkeypatch):
    """Token from env, chat_id from config — a mixed setup must work, since
    the two values are resolved separately."""
    monkeypatch.setenv(TOKEN_ENV, "env-token")
    monkeypatch.delenv(CHAT_ID_ENV, raising=False)
    token, chat_id = resolve_telegram_credentials({"telegram_chat_id": "cfg-chat"})
    assert token == "env-token"
    assert chat_id == "cfg-chat"


def test_missing_everywhere_returns_empty_strings(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(CHAT_ID_ENV, raising=False)
    token, chat_id = resolve_telegram_credentials({})
    assert token == "" and chat_id == ""


def test_none_config_is_tolerated(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "env-token")
    monkeypatch.setenv(CHAT_ID_ENV, "env-chat")
    token, chat_id = resolve_telegram_credentials(None)
    assert token == "env-token" and chat_id == "env-chat"


def test_env_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "  spaced-token  ")
    monkeypatch.setenv(CHAT_ID_ENV, "\tchat\n")
    token, chat_id = resolve_telegram_credentials({})
    assert token == "spaced-token"
    assert chat_id == "chat"


def test_unedited_example_placeholder_is_treated_as_not_set(monkeypatch):
    """Regression: a user who copies runner_config.json.example without
    editing it ends up with the literal instructional text
    'SET_VIA_KALA_TELEGRAM_TOKEN_ENV_VAR_INSTEAD' sitting in a real config.
    That string is non-empty, so before this fix it was used AS the
    credential -- reaching Telegram's real API as a bogus token and failing
    with an opaque 404, instead of main()'s clear "credentials missing"
    message. It must resolve to empty, same as if the field were blank."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(CHAT_ID_ENV, raising=False)
    token, chat_id = resolve_telegram_credentials({
        "telegram_token": "SET_VIA_KALA_TELEGRAM_TOKEN_ENV_VAR_INSTEAD",
        "telegram_chat_id": "SET_VIA_KALA_TELEGRAM_CHAT_ID_ENV_VAR_INSTEAD",
    })
    assert token == "" and chat_id == ""


def test_placeholder_in_config_does_not_block_a_real_env_var(monkeypatch):
    """The placeholder text must only blank out ITS OWN field, not somehow
    interfere with a genuinely-set env var for the same or the other key."""
    monkeypatch.setenv(TOKEN_ENV, "real-token")
    monkeypatch.delenv(CHAT_ID_ENV, raising=False)
    token, chat_id = resolve_telegram_credentials({
        "telegram_token": "SET_VIA_KALA_TELEGRAM_TOKEN_ENV_VAR_INSTEAD",
        "telegram_chat_id": "SET_VIA_KALA_TELEGRAM_CHAT_ID_ENV_VAR_INSTEAD",
    })
    assert token == "real-token"      # env wins regardless of the config placeholder
    assert chat_id == ""              # still unset: placeholder + no env


def test_a_real_looking_config_value_is_not_mistaken_for_a_placeholder():
    """Sanity check on the detection itself: an ordinary token/chat_id must
    NOT be blanked just because it happens to be an unusual string."""
    from kala.notify import _is_placeholder
    assert not _is_placeholder("123456789:AAHere-is-a-real-looking-token")
    assert not _is_placeholder("-1001234567890")
