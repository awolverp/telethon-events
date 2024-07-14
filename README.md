# Telethon events
I am created this events for me and for my usages.
I shared these to you; don't forgot to star if you like that ❤️.

**Features**:
- Full type-hint
- New event: `Command`
- `me` property added to `TelegramClient`
- Events strcuture completely changed and optimized
- `pack_bot_file_id` bug fixed
- Automatically detects spams and ignores them

**Events**:
- `NewMessage`
- `Command`
- `CallbackQuery`
- `InlineQuery`

**dependecies**:
- `telethon` - telethon library
- `cachebox` - for spam detecting

## Examples
Event examples are here.

> [!WARNING]\
> This events are completely different from telethon events. these are faster and powerful than them.

**events.Command** example:
```python
from events import TelegramClient, Command

client = TelegramClient(...)

@client.on(Command("start", private=True))
async def private_start_handler(event: Command.Event):
    await event.client.send_message(
        event.message.chat_id,
        "Hello! you sent /start command in my PV."
    )

@client.on(Command("start", public=True))
async def public_start_handler(event: Command.Event):
    await event.client.send_message(
        event.message.chat_id,
        "Hello! you sent /start command in a group."
    )

@client.on(Command(["privacy", "policy"]))
async def privacy_or_policy_handler(event: Command.Event):
    await event.client.send_message(
        event.message.chat_id,
        "PRIVACY POLICY! you sent /policy or /privacy."
    )

# ...
```


**events.NewMessage** example:
```python
from events import TelegramClient, NewMessage

client = TelegramClient(...)

@client.on(NewMessage(pattern='(?i)hello.+'))
async def hello_handler(event: NewMessage.Event):
    # Respond whenever someone says "Hello" and something else
    await event.message.reply('Hey!')

@client.on(NewMessage(outgoing=True, pattern='!ping'))
async def ping_handler(event: NewMessage.Event):
    # Say "!pong" whenever you send "!ping", then delete both messages
    m = await event.message.respond('!pong')
    await asyncio.sleep(5)
    await event.client.delete_messages(event.chat_id, [event.id, m.id])

# ...
```


**events.CallbackQuery** example:
```python
from events import TelegramClient, Command, CallbackQuery
from telethon import Button

client = TelegramClient(...)

@client.on(Command("start"))
async def start_handler(event: Command.Event):
    await event.client.send_message(
        event.message.chat_id,
        "Click Me ...",
        buttons=[
            [
                Button.inline("Dashboard", b"dashboard"),
            ],
            [
                Button.inline("First Panel", b"panel/first"),
                Button.inline("Second Panel", b"panel/second")
            ],
            [
                Button.inline("Yes", b"confirm"),
                Button.inline("No", b"confirm_no"),
            ]
        ]
    )

# Handle exactly `dashboard`
@client.on(CallbackQuery("dashboard"))
async def handler(event: CallbackQuery.Event):
    await event.edit(
        "welcome to dashboard"
    )

# Handle `panel/...`
# Now this handles `panel/first` and `panel/second` queries for us.
@client.on(CallbackQuery("panel", split=("/", 1)))
async def panel(event: CallbackQuery.Event):
    await event.edit(
        "welcome to panel"
    )

# Handle `confirm` or `confirm_...` or `confirm_..._...`
# Now this handles `confirm` and `confirm_no` queries for us.
# Without specifying the `_` count, there's no care about count of that
@client.on(CallbackQuery("confirm", split="_"))
async def panel(event: CallbackQuery.Event):
    await event.edit(
        "welcome to panel"
    )

# ...
```

**events.InlineQuery** example:
```python
from events import TelegramClient, InlineQuery

client = TelegramClient(...)

@client.on(InlineQuery)
async def handler(event):
    builder = event.builder

    # Two options (convert user text to UPPERCASE or lowercase)
    await event.answer([
        builder.article('UPPERCASE', text=event.text.upper()),
        builder.article('lowercase', text=event.text.lower()),
    ])

# ...
```
