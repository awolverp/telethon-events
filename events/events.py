# MIT License
# Copyright (c) 2024 awolverp

from telethon.events.common import EventCommon
from telethon.tl.custom.sendergetter import SenderGetter
from telethon.tl import types, custom
from telethon import utils, functions, helpers, TelegramClient as _BaseTelegramClient

import asyncio
import inspect
import struct
import typing
import abc
import re

import cachebox
_spam_cache = cachebox.TTLCache(500, 0.6)

def is_spam(id: int) -> bool:
    if _spam_cache.get(id, 0):
        return True

    _spam_cache[id] = 1
    return False


class TelegramClient(_BaseTelegramClient):
    """
    Override `telethon.TelegramClient` to add `.me` attribute.
    """

    me: types.User

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        self.me = await self.get_me()


class EventBuilder(abc.ABC):
    def __init__(self, func=None):
        self.resolved = False
        self.func = func

    @classmethod
    @abc.abstractmethod
    def build(cls, update, others=None, self_id=None):
        pass

    async def resolve(self, _):
        if self.resolved:
            return

        self.resolved = True

    def filter(self, event):
        if not self.resolved:
            return

        if self.func is not None:
            return self.func(event)

        return True


class _EventCommon(EventCommon):
    _client: TelegramClient

    @property
    def client(self) -> TelegramClient:
        """
        The `TelegramClient` that created this event.
        """
        return self._client


class NewMessage(EventBuilder):
    def __init__(
        self,
        pattern: typing.Union[str, re.Pattern, None] = None,
        outgoing: typing.Optional[bool] = None,
        incoming: typing.Optional[bool] = None,
        func: typing.Optional[typing.Callable[["NewMessage.Event"], bool]] = None,
        private: bool = False,
        public: bool = False,
    ) -> None:
        """
        Occurs whenever a new text message or a message with media arrives.

        Note:
            Use `Command` for handling commands which are starts by `/`.

        Args:
            incoming (`bool`, optional):
                If set to `True`, only **incoming** messages will be handled.
                Mutually exclusive with ``outgoing`` (can only set one of either).

            outgoing (`bool`, optional):
                If set to `True`, only **outgoing** messages will be handled.
                Mutually exclusive with ``incoming`` (can only set one of either).

            pattern (`str`, `Pattern`, optional):
                If set, only messages matching this pattern will be handled.
                You can specify a regex-like string which will be matched
                against the message, a callable function that returns `True`
                if a message is acceptable, or a compiled regex pattern.

            private (`bool`, optional):
                If set, only private messages will be handled.

            public (`bool`, optional):
                If set, only private messages will be handled.
        """
        super().__init__(func=func)

        if private and public:
            raise ValueError(
                "What are you doing? a message can't be in both of private and public chats!"
            )

        if incoming and outgoing:
            incoming = outgoing = None  # Same as no filter
        elif incoming is not None and outgoing is None:
            outgoing = not incoming
        elif outgoing is not None and incoming is None:
            incoming = not outgoing
        elif all(x is not None and not x for x in (incoming, outgoing)):
            raise ValueError(
                "Don't create an event handler if you " "don't want neither incoming nor outgoing!"
            )

        if isinstance(pattern, str):
            self.pattern = re.compile(pattern)
        elif isinstance(pattern, re.Pattern):
            self.pattern = pattern
        elif pattern is None:
            self.pattern = None
        else:
            raise TypeError(
                "The `pattern` argument should be string, re.Pattern, or None. got %r"
                % (type(pattern).__name__)
            )

        self.incoming = incoming
        self.outgoing = outgoing
        self.private = private
        self.public = public

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
            if not isinstance(update.message, types.Message):
                return  # We don't care about MessageService's here
            event = cls.Event(update.message)
        elif isinstance(update, types.UpdateShortMessage):
            event = cls.Event(
                types.Message(
                    out=update.out,
                    mentioned=update.mentioned,
                    media_unread=update.media_unread,
                    silent=update.silent,
                    id=update.id,
                    peer_id=types.PeerUser(update.user_id),
                    from_id=types.PeerUser(self_id if update.out else update.user_id),
                    message=update.message,
                    date=update.date,
                    fwd_from=update.fwd_from,
                    via_bot_id=update.via_bot_id,
                    reply_to=update.reply_to,
                    entities=update.entities,
                    ttl_period=update.ttl_period,
                )
            )
        elif isinstance(update, types.UpdateShortChatMessage):
            event = cls.Event(
                types.Message(
                    out=update.out,
                    mentioned=update.mentioned,
                    media_unread=update.media_unread,
                    silent=update.silent,
                    id=update.id,
                    from_id=types.PeerUser(self_id if update.out else update.from_id),
                    peer_id=types.PeerChat(update.chat_id),
                    message=update.message,
                    date=update.date,
                    fwd_from=update.fwd_from,
                    via_bot_id=update.via_bot_id,
                    reply_to=update.reply_to,
                    entities=update.entities,
                    ttl_period=update.ttl_period,
                )
            )
        else:
            return

        return event

    def filter(self, event: "NewMessage.Event"):
        if self.private and not event.is_private:
            return

        if self.public and not (event.is_group or event.is_channel):
            return

        if self.incoming and event.message.out:
            return

        if self.outgoing and not event.message.out:
            return

        if self.pattern:
            match = self.pattern.match(event.message.message or "")
            if not match:
                return

        if is_spam(event.message.sender_id):
            return

        return super().filter(event)

    class Event(_EventCommon):
        def __init__(self, message):
            self.__dict__["_init"] = False
            super().__init__(
                chat_peer=message.peer_id,
                msg_id=message.id,
                broadcast=bool(message.post),
            )

            self.message: custom.Message = message

        def _set_client(self, client):
            super()._set_client(client)
            m = self.message
            m._finish_init(client, self._entities, None)
            self.__dict__["_init"] = True  # No new attributes can be set

        def __getattr__(self, item):
            return self.__dict__[item]

        def __setattr__(self, name, value):
            if not self.__dict__["_init"] or name in self.__dict__:
                self.__dict__[name] = value


class Command(NewMessage):
    def __init__(
        self,
        command: typing.Union[typing.List[str], str],
        outgoing: typing.Optional[bool] = None,
        incoming: typing.Optional[bool] = None,
        func: typing.Optional[typing.Callable[["Command.Event"], bool]] = None,
        private: bool = False,
        public: bool = False,
    ) -> None:
        """
        Works like `NewMessage` but is specially for commands.
        This structure detects commands which are started by `/` as fast as possible.

        Args:
            command (`list[str]`, `str`):
                A list of commands (or a command) that you want to be handled.
                There's no way to specify first letter (`/`) here.
                For example: `["start", "panel"]`

            incoming (`bool`, optional):
                If set to `True`, only **incoming** messages will be handled.
                Mutually exclusive with ``outgoing`` (can only set one of either).

            outgoing (`bool`, optional):
                If set to `True`, only **outgoing** messages will be handled.
                Mutually exclusive with ``incoming`` (can only set one of either).

            private (`bool`, optional):
                If set, only private messages will be handled.

            public (`bool`, optional):
                If set, only private messages will be handled.
        """
        if isinstance(command, str):
            self.command = [command.replace("/", "", 1)]

        elif isinstance(command, list):
            self.command = [i.replace("/", "", 1) for i in command]

        else:
            raise TypeError(
                "The `command` argument should be string, or list. got %r"
                % (type(command).__name__)
            )

        super().__init__(
            None,
            outgoing=outgoing,
            incoming=incoming,
            func=func,
            private=private,
            public=public,
        )

    def filter(self, event: "Command.Event"):
        if self.private and not event.message.is_private:
            return

        if self.public and not (event.message.is_group or event.message.is_channel):
            return

        if self.incoming and event.message.out:
            return

        if self.outgoing and not event.message.out:
            return

        if (
            (not event.message.entities)
            or (not isinstance(event.message.entities[0], types.MessageEntityBotCommand))
            or (event.message.entities[0].offset != 0)
        ):
            return

        _entity_command = event.message.message[
            event.message.entities[0].offset + 1 : event.message.entities[0].offset
            + event.message.entities[0].length
        ].split("@")

        if _entity_command.pop(0) not in self.command:
            return

        if _entity_command and (_entity_command[0] != event._client.me.username):
            return
        
        if is_spam(event.message.sender_id):
            return

        # we don't need to call NewMessage.filter, so we couldn't use `super` here.
        return EventBuilder.filter(self, event)


class CallbackQuery(EventBuilder):
    def __init__(
        self,
        data: typing.Union[str, bytes, None] = None,
        split: typing.Union[typing.Tuple[typing.Union[str, bytes], int], str, bytes, None] = None,
        func: typing.Optional[typing.Callable[["CallbackQuery.Event"], bool]] = None,
    ) -> None:
        """
        Occurs whenever you sign in as a bot and a user
        clicks one of the inline buttons on your messages.

        Note that the `chats` parameter will **not** work with normal
        IDs or peers if the clicked inline button comes from a "via bot"
        message. The `chats` parameter also supports checking against the
        `chat_instance` which should be used for inline callbacks.

        Args:
            data (`str`, `bytes`, optional):
                If set, the inline button payload data must match this data.
                for instance if you pass `mydata`, only callbacks whose data
                is `mydata` are handled.

            split (`tuple[str | bytes, int]`, `str`, `bytes`, optional):
                If set, the checking process will be different. for instance,
                to check against `'mydata/1'` and `'mydata/hi/hello'` you
                can use `data="mydata", split="/"`;
                and if you want data to have exactly only one `/` in that, you can
                set `split=("/", 1)`.

        Examples::

            # this handles exactly `panel`
            CallbackQuery("panel")

            # this handles `manage`, `manage/other`, `manage/one/two` ...
            CallbackQuery("manage", split="/")

            # this handles `manage/`, `manage/other`, `manage/one` ...
            CallbackQuery("manage", split=("/", 1))

            # this handles `manage_1_2`, `manage_other_hi`, `manage_one_two` ...
            CallbackQuery("manage", split=("_", 2))
        """
        super().__init__(func=func)

        if isinstance(data, str):
            data = data.encode("utf-8")

        self.data = data

        if isinstance(split, tuple):
            self.split_char = split[0]
            self.split_char_count = split[1]
        else:
            self.split_char = split
            self.split_char_count = None

        if isinstance(self.split_char, str):
            self.split_char = self.split_char.encode("utf-8")

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, types.UpdateBotCallbackQuery):
            return cls.Event(update, update.peer, update.msg_id)
        elif isinstance(update, types.UpdateInlineBotCallbackQuery):
            # See https://github.com/LonamiWebs/Telethon/pull/1005
            # The long message ID is actually just msg_id + peer_id
            mid, pid = struct.unpack("<ii", struct.pack("<q", update.msg_id.id))
            peer = types.PeerChannel(-pid) if pid < 0 else types.PeerUser(pid)
            return cls.Event(update, peer, mid)

    def filter(self, event: "CallbackQuery.Event"):
        if self.data:
            # This structure is very faster than regexp
            if (not self.split_char) and self.data != event.query.data:
                return

            else:
                if (
                    self.split_char_count
                    and event.query.data.count(self.split_char) != self.split_char_count
                ):
                    return

                if self.data != event.query.data.split(self.split_char, 2)[0]:
                    return
        
        if is_spam(event.query.user_id):
            return

        return super().filter(event)

    class Event(_EventCommon, SenderGetter):
        def __init__(self, query, peer, msg_id):
            super().__init__(peer, msg_id=msg_id)
            SenderGetter.__init__(self, query.user_id)
            self.query: typing.Union[
                types.UpdateBotCallbackQuery, types.UpdateInlineBotCallbackQuery
            ] = query

            self._message = None
            self._answered = False

        def _set_client(self, client):
            super()._set_client(client)
            self._sender, self._input_sender = utils._get_entity_pair(
                self.sender_id, self._entities, client._mb_entity_cache
            )

        @property
        def id(self):
            """
            Returns the query ID. The user clicking the inline
            button is the one who generated this random ID.
            """
            return self.query.query_id

        @property
        def message_id(self):
            """
            Returns the message ID to which the clicked inline button belongs.
            """
            return self._message_id

        @property
        def data(self):
            """
            Returns the data payload from the original inline button.
            """
            return self.query.data

        @property
        def chat_instance(self):
            """
            Unique identifier for the chat where the callback occurred.
            Useful for high scores in games.
            """
            return self.query.chat_instance

        async def get_message(self):
            """
            Returns the message to which the clicked inline button belongs.
            """
            if self._message is not None:
                return self._message

            try:
                chat = await self.get_input_chat() if self.is_channel else None
                self._message = await self._client.get_messages(chat, ids=self._message_id)
            except ValueError:
                return

            return self._message

        async def _refetch_sender(self):
            self._sender = self._entities.get(self.sender_id)
            if not self._sender:
                return

            self._input_sender = utils.get_input_peer(self._chat)
            if not getattr(self._input_sender, "access_hash", True):
                # getattr with True to handle the InputPeerSelf() case
                try:
                    self._input_sender = self._client._mb_entity_cache.get(
                        utils.resolve_id(self._sender_id)[0]
                    )._as_input_peer()
                except AttributeError:
                    m = await self.get_message()
                    if m:
                        self._sender = m._sender
                        self._input_sender = m._input_sender

        async def answer(self, message=None, cache_time=0, *, url=None, alert=False):
            """
            Answers the callback query (and stops the loading circle).

            Args:
                message (`str`, optional):
                    The toast message to show feedback to the user.

                cache_time (`int`, optional):
                    For how long this result should be cached on
                    the user's client. Defaults to 0 for no cache.

                url (`str`, optional):
                    The URL to be opened in the user's client. Note that
                    the only valid URLs are those of games your bot has,
                    or alternatively a 't.me/your_bot?start=xyz' parameter.

                alert (`bool`, optional):
                    Whether an alert (a pop-up dialog) should be used
                    instead of showing a toast. Defaults to `False`.
            """
            if self._answered:
                return

            self._answered = True
            return await self._client(
                functions.messages.SetBotCallbackAnswerRequest(
                    query_id=self.query.query_id,
                    cache_time=cache_time,
                    alert=alert,
                    message=message,
                    url=url,
                )
            )

        @property
        def via_inline(self):
            """
            Whether this callback was generated from an inline button sent
            via an inline query or not. If the bot sent the message itself
            with buttons, and one of those is clicked, this will be `False`.
            If a user sent the message coming from an inline query to the
            bot, and one of those is clicked, this will be `True`.

            If it's `True`, it's likely that the bot is **not** in the
            chat, so methods like `respond` or `delete` won't work (but
            `edit` will always work).
            """
            return isinstance(self.query, types.UpdateInlineBotCallbackQuery)

        async def respond(self, *args, **kwargs):
            """
            Responds to the message (not as a reply). Shorthand for
            `telethon.client.messages.MessageMethods.send_message` with
            ``entity`` already set.

            This method also creates a task to `answer` the callback.

            This method will likely fail if `via_inline` is `True`.
            """
            self._client.loop.create_task(self.answer())
            return await self._client.send_message(await self.get_input_chat(), *args, **kwargs)

        async def reply(self, *args, **kwargs):
            """
            Replies to the message (as a reply). Shorthand for
            `telethon.client.messages.MessageMethods.send_message` with
            both ``entity`` and ``reply_to`` already set.

            This method also creates a task to `answer` the callback.

            This method will likely fail if `via_inline` is `True`.
            """
            self._client.loop.create_task(self.answer())
            kwargs["reply_to"] = self.query.msg_id
            return await self._client.send_message(await self.get_input_chat(), *args, **kwargs)

        async def edit(self, *args, **kwargs):
            """
            Edits the message. Shorthand for
            `telethon.client.messages.MessageMethods.edit_message` with
            the ``entity`` set to the correct :tl:`InputBotInlineMessageID` or :tl:`InputBotInlineMessageID64`.

            Returns `True` if the edit was successful.

            This method also creates a task to `answer` the callback.

            .. note::

                This method won't respect the previous message unlike
                `Message.edit <telethon.tl.custom.message.Message.edit>`,
                since the message object is normally not present.
            """
            self._client.loop.create_task(self.answer())
            if isinstance(
                self.query.msg_id, (types.InputBotInlineMessageID, types.InputBotInlineMessageID64)
            ):
                return await self._client.edit_message(self.query.msg_id, *args, **kwargs)
            else:
                return await self._client.edit_message(
                    await self.get_input_chat(), self.query.msg_id, *args, **kwargs
                )

        async def delete(self, *args, **kwargs):
            """
            Deletes the message. Shorthand for
            `telethon.client.messages.MessageMethods.delete_messages` with
            ``entity`` and ``message_ids`` already set.

            If you need to delete more than one message at once, don't use
            this `delete` method. Use a
            `telethon.client.telegramclient.TelegramClient` instance directly.

            This method also creates a task to `answer` the callback.

            This method will likely fail if `via_inline` is `True`.
            """
            self._client.loop.create_task(self.answer())
            if isinstance(
                self.query.msg_id, (types.InputBotInlineMessageID, types.InputBotInlineMessageID64)
            ):
                raise TypeError(
                    "Inline messages cannot be deleted as there is no API request available to do so"
                )
            return await self._client.delete_messages(
                await self.get_input_chat(), [self.query.msg_id], *args, **kwargs
            )


class InlineQuery(EventBuilder):
    def __init__(
        self,
        pattern: typing.Union[str, re.Pattern, None] = None,
        func: typing.Optional[typing.Callable[["InlineQuery.Event"], bool]] = None,
    ) -> None:
        """
        Occurs whenever you sign in as a bot and a user
        sends an inline query such as ``@bot query``.

        Args:
            pattern (`str`, `Pattern`, optional):
                If set, only queries matching this pattern will be handled.
                You can specify a regex-like string which will be matched
                against the message, a callable function that returns `True`
                if a message is acceptable, or a compiled regex pattern.
        """
        super().__init__(func=func)

        if isinstance(pattern, str):
            self.pattern = re.compile(pattern)
        elif isinstance(pattern, re.Pattern):
            self.pattern = pattern
        elif pattern is None:
            self.pattern = None
        else:
            raise TypeError(
                "The `pattern` argument should be string, re.Pattern, or None. got %r"
                % (type(pattern).__name__)
            )

    @classmethod
    def build(cls, update, others=None, self_id=None):
        if isinstance(update, types.UpdateBotInlineQuery):
            return cls.Event(update)

    def filter(self, event: "InlineQuery.Event"):
        if self.pattern:
            match = self.pattern.match(event.query.query or "")
            if not match:
                return

        return super().filter(event)

    class Event(_EventCommon, SenderGetter):
        def __init__(self, query):
            super().__init__(chat_peer=types.PeerUser(query.user_id))
            SenderGetter.__init__(self, query.user_id)
            self.query: types.UpdateBotInlineQuery = query
            self._answered = False

        def _set_client(self, client):
            super()._set_client(client)
            self._sender, self._input_sender = utils._get_entity_pair(
                self.sender_id, self._entities, client._mb_entity_cache
            )

        @property
        def id(self):
            """
            Returns the unique identifier for the query ID.
            """
            return self.query.query_id

        @property
        def text(self):
            """
            Returns the text the user used to make the inline query.
            """
            return self.query.query

        @property
        def offset(self):
            """
            The string the user's client used as an offset for the query.
            This will either be empty or equal to offsets passed to `answer`.
            """
            return self.query.offset

        @property
        def geo(self):
            """
            If the user location is requested when using inline mode
            and the user's device is able to send it, this will return
            the :tl:`GeoPoint` with the position of the user.
            """
            return self.query.geo

        @property
        def builder(self):
            """
            Returns a new `InlineBuilder
            <telethon.tl.custom.inlinebuilder.InlineBuilder>` instance.
            """
            return custom.InlineBuilder(self._client)

        async def answer(
            self,
            results=None,
            cache_time=0,
            *,
            gallery=False,
            next_offset=None,
            private=False,
            switch_pm=None,
            switch_pm_param="",
        ):
            """
            Answers the inline query with the given results.

            See the documentation for `builder` to know what kind of answers
            can be given.

            Args:
                results (`list`, optional):
                    A list of :tl:`InputBotInlineResult` to use.
                    You should use `builder` to create these:

                    .. code-block:: python

                        builder = inline.builder
                        r1 = builder.article('Be nice', text='Have a nice day')
                        r2 = builder.article('Be bad', text="I don't like you")
                        await inline.answer([r1, r2])

                    You can send up to 50 results as documented in
                    https://core.telegram.org/bots/api#answerinlinequery.
                    Sending more will raise ``ResultsTooMuchError``,
                    and you should consider using `next_offset` to
                    paginate them.

                cache_time (`int`, optional):
                    For how long this result should be cached on
                    the user's client. Defaults to 0 for no cache.

                gallery (`bool`, optional):
                    Whether the results should show as a gallery (grid) or not.

                next_offset (`str`, optional):
                    The offset the client will send when the user scrolls the
                    results and it repeats the request.

                private (`bool`, optional):
                    Whether the results should be cached by Telegram
                    (not private) or by the user's client (private).

                switch_pm (`str`, optional):
                    If set, this text will be shown in the results
                    to allow the user to switch to private messages.

                switch_pm_param (`str`, optional):
                    Optional parameter to start the bot with if
                    `switch_pm` was used.

            Example:

                .. code-block:: python

                    @bot.on(events.InlineQuery)
                    async def handler(event):
                        builder = event.builder

                        rev_text = event.text[::-1]
                        await event.answer([
                            builder.article('Reverse text', text=rev_text),
                            builder.photo('/path/to/photo.jpg')
                        ])
            """
            if self._answered:
                return

            if results:
                futures = [self._as_future(x) for x in results]

                await asyncio.wait(futures)

                # All futures will be in the `done` *set* that `wait` returns.
                #
                # Precisely because it's a `set` and not a `list`, it
                # will not preserve the order, but since all futures
                # completed we can use our original, ordered `list`.
                results = [x.result() for x in futures]
            else:
                results = []

            if switch_pm:
                switch_pm = types.InlineBotSwitchPM(switch_pm, switch_pm_param)

            return await self._client(
                functions.messages.SetInlineBotResultsRequest(
                    query_id=self.query.query_id,
                    results=results,
                    cache_time=cache_time,
                    gallery=gallery,
                    next_offset=next_offset,
                    private=private,
                    switch_pm=switch_pm,
                )
            )

        @staticmethod
        def _as_future(obj):
            if inspect.isawaitable(obj):
                return asyncio.ensure_future(obj)

            f = helpers.get_running_loop().create_future()
            f.set_result(obj)
            return f
