import asyncio

import discord

from dncore.util.instance import get_core


def replace_overrides():
    discord.Message.delete = _Message.delete


class _Message(discord.Message):
    async def delete(self, *, delay: float = None) -> None:
        """|coro|

        Deletes the message.

        Your own messages could be deleted without any proper permissions. However to
        delete other people's messages, you must have :attr:`~Permissions.manage_messages`.

        .. versionchanged:: 1.1
            Added the new ``delay`` keyword-only parameter.

        Parameters
        -----------
        delay: Optional[:class:`float`]
            If provided, the number of seconds to wait in the background
            before deleting the message. If the deletion fails then it is silently ignored.

        Raises
        ------
        Forbidden
            You do not have proper permissions to delete the message.
        NotFound
            The message was deleted already
        HTTPException
            Deleting the message failed.
        """
        if delay is not None:

            async def delete(delay: float):
                await asyncio.sleep(delay)
                client = get_core().connected_client
                if client:
                    try:
                        await client.http.delete_message(self.channel.id, self.id)
                    except discord.HTTPException:
                        pass

            asyncio.create_task(delete(delay))
        else:
            await self._state.http.delete_message(self.channel.id, self.id)
