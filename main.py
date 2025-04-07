import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import time
import typing
import json
import os
import log
import filehelper
import predicate
import kwargparse

async def setup(bot: commands.Bot):
    await bot.add_cog(BAM(bot))
    log.info("BAM extension loaded")

async def teardown(bot: commands.Bot):
    await bot.remove_cog("BAM")
    log.info("BAM extension unloaded")

class BAM(commands.Cog):
    def __init__(self, bot):
        log.info("BAM Cog initialize...")
        self.bot: commands.Bot = bot
        self.msg_tracked: dict[str, any] = {}
        self.config = filehelper.openConfig('bam')
        self.roles_detection: list = self.config.get("roles") or list()
        self.periodic_scan_enabled = self.config.get("periodic_scan_enabled") or False
        self.periodic_scan.change_interval(minutes=self.config.get("periodic_scan_interval") or 60)
        self.tracked_msg_save_file = "tracked_messages.bam.json"
        try:
            self.tracked_msg_save_file = self.config["save_path"]["tracked_messages"]
        except:
            pass

    def load_tracked_messages(self):
        # Create the directory if it doesn't exist
        filehelper.ensure_directory("save")
        self.msg_tracked = filehelper.openJson("save", self.tracked_msg_save_file) or {}
        log.info(f"Tracked messages loaded from {self.tracked_msg_save_file}: {self.msg_tracked}")

    def save_tracked_messages(self):
        filehelper.saveJson("save", self.tracked_msg_save_file, self.msg_tracked)
        log.info(f"Tracked messages saved to {self.tracked_msg_save_file}: {self.msg_tracked}")

    @tasks.loop(seconds=10)
    async def periodic_scan(self):
        try:
            log.info("Executing periodic scan...")
            await self.fetch_roles()
        except Exception as e:
            log.error(f"Failed to execute periodic scan: {e}")

    def start_periodic_scan(self):
        if self.periodic_scan_enabled:
            log.info("Starting perdiodic scan...")
            self.periodic_scan.start()

    def stop_periodic_scan(self):
        if self.periodic_scan.is_running():
            log.info("Cancelling perdiodic scan...")
            self.periodic_scan.cancel()

    # Cog startup
    async def cog_load(self):
        log.info("BAM module startup!")
        self.load_tracked_messages()
        self.start_periodic_scan()
    
    # Cog cleanup
    async def cog_unload(self):
        log.info("BAM module cleanup!")
        self.stop_periodic_scan()
        self.save_tracked_messages()
        self.config["roles"] = self.roles_detection
        filehelper.saveConfig(module="bam", data=self.config)

    # Try to retrieve a message from a channel
    async def get_message(self, channel_id: int, message_id: int) -> typing.Optional[discord.Message]:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            log.error(f"Channel not found: {channel_id}")
            return None

        message = None
        try:
            message = await channel.fetch_message(message_id)
            log.info("Message found!")
        except discord.NotFound:
            log.error("Message not found")
        except discord.Forbidden:
            log.error("Not allowed to access this channel")
        except Exception as e:
            log.error(f"Failed to get message: {e}")

        return message

    # Send a message in a channel and track this message for later deletion
    # returns True when the message has been sent, false otherwise
    async def send_role_message(self, role_id: int, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, message: str, resend: bool = False, forceResendDelay: int = 60, replyParent: discord.Message = None) -> bool:
        try:
            key = f"{guild.id}-{member.id}"

            # Check if a message has already been sent to this user
            msgDataList = self.msg_tracked.get(key)
            if msgDataList is not None:
                msgData = None
                for msgDatum in msgDataList:
                    if msgDatum["role"] == role_id:
                        msgData = msgDatum
                        break
                
                try:
                    elapsed_minutes = (datetime.datetime.fromtimestamp(time.time()) - datetime.datetime.fromtimestamp(msgData["timestamp"])).total_seconds() / 60
                    log.info(f"Message already sent to {member.name} ({member.id}) in {guild.name} ({guild.id}), (elapsed minutes since last message: {elapsed_minutes}).")
                    if elapsed_minutes > forceResendDelay:
                        resend = True
                        log.info(f"Forcing resend (>{forceResendDelay} minutes).")
                    else:
                        log.info(f"Not resending message (<{forceResendDelay} minutes).")
                except Exception as e:
                    log.error(f"Failed to retrieve tracked message timestamp: {e}")
                    
                if not resend:
                    # Do not send message if already sent
                    return False
                else:
                    # Delete previous message if resend is True
                    await self.delete_role_message(key)

            if replyParent is None:
                msg = await channel.send(message.format(user_id=member.id))
            else:
                msg = await replyParent.reply(message.format(user_id=member.id), mention_author=True)
            if self.msg_tracked.get(key) is None:
                self.msg_tracked[key] = []

            self.msg_tracked[key].append({"role": role_id, "guild": msg.guild.id, "channel": msg.channel.id, "id": msg.id, "timestamp": msg.created_at.timestamp()});
        
            log.info(f"Message tracked: {key}")
            return True
        except Exception as e:
            log.error(f"Failed to send message: {e}")
        return False

    async def delete_role_message(self, key: str):
        for msgData in self.msg_tracked.get(key):
            try:
                msg = await self.get_message(msgData["channel"], msgData["id"])
                await msg.delete()
                del self.msg_tracked[key]
                log.info(f"Message untracked {key}")
            except Exception as e:
                log.error(f"Failed to delete message: {e}")

    # Just log for now when a member joins the server
    @commands.Cog.listener()
    async def on_member_join(self, member):
        log.info(f"Member {member.name} ({member.id}) joined {member.guild.name}")

    # Detect when a member updates their roles
    # and send a message in the specified channel if the role is detected
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        before_roles = set(role.id for role in before.roles)
        after_roles = set(role.id for role in after.roles)
        new_roles = after_roles - before_roles

        log.info(f"Member {after.name} ({after.id}) updated in {after.guild.name}. New roles: {new_roles}")

        await self.send_message(after, after.guild)

    # Delete the tracked message when the member leaves the server
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        log.info(f"Member {member.name} ({member.id}) removed from {member.guild.name} ({member.guild.id})")
        key = f"{member.guild.id}-{member.id}"
        await self.delete_role_message(key)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not isinstance(message.author, discord.Member):
            return
        
        for role_to_detect in self.roles_detection:
            if not role_to_detect["enabled"]:
                continue
            emoji = role_to_detect.get("emoji")
            if not emoji:
                continue
            if role_to_detect["id"] in [role.id for role in message.author.roles]:
                log.info(f"React to message with emoji {emoji}")
                try:
                    await message.add_reaction(emoji)
                except Exception as e:
                    log.error(f"Failed to add rection to message {message.id}")
                break

        await self.send_message(message.author, message.guild, replyParent=message)

    # Send tracked role message
    async def send_message(self, member: discord.Member, guild: discord.Guild, replyParent: discord.Message = None):
        for role_to_detect in self.roles_detection:
            if not role_to_detect["enabled"]:
                continue
            if role_to_detect["id"] in [role.id for role in member.roles]:
                log.info(f"Detected role {role_to_detect['id']} for {member.name} ({member.id}) in {member.name}")
                channel = self.bot.get_channel(role_to_detect["channel_notif"])
                if not channel:
                    log.error("No channel to send the message.")
                    continue
                await self.send_role_message(role_to_detect["id"], guild, member, channel, role_to_detect["message"], replyParent=replyParent)

    ####                                  ####
    #       Role Configuration Commands      #
    ####                                  ####

    def get_role_config(self, role: discord.Role):
        for role_config in self.roles_detection:
            if role_config["id"] == role.id:
                return role_config
        return None

    def get_role_info(self, role: discord.Role) -> str:
        role_config = self.get_role_config(role)
        # Write basic role info
        role_info: str = f"**Role {role.name}**\n\
**ID**: {role.id}\n\
**Creation**: {role.created_at.strftime('%a, %d %b %Y %I:%M %p')}\n\
**Position**: {role.position}\n\
**Mentionable**: {role.mentionable}\n\
**Tracked**: {role_config is not None}\n"

        # Appends track info if possible
        if role_config is not None:
            role_info += f"**Enabled**: {':white_check_mark:' if role_config['enabled'] else ':x:'}\n\
**Notif Channel**: {role_config['channel_notif']}\n\
**Cooldown**: {role_config['cooldown']}\n\
**Emoji**: {role_config['emoji']}\n\
**Message**: {role_config['message']}"
        
        return role_info

    async def get_channel(self, channel_id: int) -> typing.Optional[discord.TextChannel]:
        # Try to get the channel from the cache
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                # Fetch the channel from the API if not in cache
                channel = await self.bot.fetch_channel(channel_id)
            except discord.NotFound:
                print(f"Channel with ID {channel_id} not found.")
            except discord.Forbidden:
                print(f"Bot does not have permission to access channel with ID {channel_id}.")
            except Exception as e:
                print(f"An error occurred while fetching the channel: {e}")
        return channel

    async def get_role(self, ctx: commands.Context, role_id: int) -> typing.Optional[discord.Role]:
        # Search through all guilds the bot is in
        for guild in self.bot.guilds:
            role = guild.get_role(role_id)
            if role is not None:
                return role
        
        # Role not found in any guild
        log.error(f"Role with ID {role_id} not found in any guild.")
        return None

    async def enable_role(self, ctx: commands.Context, role: discord.Role, enable: bool) -> None:
        role_config = self.get_role_config(role)
        if role_config is None:
            await log.failure(ctx, f"Role `{role.name}` ({role.id}) is not configured yet.")
            return
        
        role_config["enabled"] = enable
        log.info(f"{'En' if enable else 'Dis'}abling role `{role.name}` ({role.id})")
        await log.client(ctx, f"Role `{role.name}` ({role.id}) tracking status: {':white_check_mark:' if enable else ':x:'}")

    @commands.command()
    @predicate.admin_only()
    async def role(self, ctx: commands.Context, role: discord.Role = None, command: str = None, *, args: str = None):
        await ctx.message.delete()

        if role is None: # List all tracked roles if no role provided
            log.info("Displaying all tracked roles.")
            role_list = "Tracked roles:\n"
            for role_config in self.roles_detection:
                role = await self.get_role(ctx, role_config['id'])
                if role is not None:
                    role_list += f"- Role `{role.name}` ({role.id}) in channel {role_config['channel_notif']} (enabled: {role_config['enabled']})\n"
            await log.client(ctx, role_list, delete_after=20)

        elif command is None: # Display role informations if no command provided
            try:
                await log.client(ctx, self.get_role_info(role), delete_after=20)
            except Exception as e:
                await log.failure(ctx, f"Failed to retrieve role information: {e}")
        
        elif command.lower() == "enable": # Enable or disable a specific role (assume "enable on" if no argument passed)
            enable = True
            if args is not None:
                try:
                    enable = await commands.run_converters(ctx, bool, args, {})
                except Exception as e:
                    await log.failure(ctx, f"Failed to get boolean argument: {e}")
                    return
            await self.enable_role(ctx, role, enable)
        
        elif command.lower() == "disable": # Shortcut for "enable off"
            await self.enable_role(ctx, role, False)

        elif command.lower() == "track": # Track a new role
            role_config = self.get_role_config(role)
            if role_config is not None:
                await log.failure(ctx, f"Role `{role.name}` ({role.id}) is already configured.")
                return
            
            kwargs: dict[str, str] = dict()
            if args is not None:
                try:
                    log.info(f"Args: {args}")
                    kwargs = kwargparse.parse_kwargs(args)
                    log.info(f"Result: {kwargs}")
                except kwargparse.UnexpectedToken as e:
                    await log.failure(ctx, f"Unexpected token: {e}", delete_after=20)
                    return
            
            log.info(f"Try to configure role `{role.name}` ({role.id}).")

            # Add the new role to the list
            new_role_config = {
                "enabled": False,
                "id": role.id,
                "channel_notif": kwargs.get("channel") or ctx.channel.id,
                "emoji": kwargs.get("emoji"),
                "cooldown": kwargs.get("cooldown") or 60,
                "message": kwargs.get("message") or "Default message. Use `role @role message <msg>` to change it."
            }
            self.roles_detection.append(new_role_config)
            await log.success(ctx, f"Role `{role.name}` ({role.id}) now configured. Use `role @role enable` to enable it.")

        elif command.lower() == "untrack": # Untrack a role
            role_config = self.get_role_config(role)
            if role_config is None:
                await log.failure(ctx, f"Role is not configured yet.")
                return
            
            log.info(f"Try to untrack role `{role.name}` ({role.id}).")
            for i, tracked_role in enumerate(self.roles_detection):
                if tracked_role["id"] == role.id:
                    del self.roles_detection[i]
                    await log.success(ctx, f"Role `{role.name}` ({role.id}) now untracked.")

        elif command.lower() == "channel": # Change or display the notification channel
            role_config = self.get_role_config(role)
            if role_config is None:
                await log.failure(ctx, f"Role is not configured yet.")
                return
            
            if args is None: # Display current notif channel if no argument provided
                channel: discord.TextChannel = await self.get_channel(role_config["channel_notif"])
                await log.client(ctx, f"Notification channel for `{role.name}` ({role.id}) is set to `{channel.name}` ({channel.id})")
            else:
                try:
                    log.info(f"Try to set channel's role `{role.name}` ({role.id}) to {args}.")
                    converter = commands.TextChannelConverter()
                    channel = await converter.convert(ctx, args)
                    role_config["channel_notif"] = channel.id
                    await log.success(ctx, f"Notification channel for `{role.name}` ({role.id}) successfully set to: `{channel}`")
                except Exception as e:
                    await log.failure(ctx, f"Failed to retrieve channel: {e}")

        elif command.lower() == "emoji": # Change or display the emoji
            role_config = self.get_role_config(role)
            if role_config is None:
                await log.failure(ctx, f"Role is not configured yet.")
                return
            
            if args is None: # Display current notif channel if no argument provided
                await log.client(ctx, f"Emoji for `{role.name}` ({role.id}) is set to {role_config["emoji"]}")
            else:
                log.info(f"Try to set emoji's role `{role.name}` ({role.id}) to {args}.")
                role_config["emoji"] = args
                await log.success(ctx, f"Emoji for `{role.name}` ({role.id}) successfully set to: `{role_config["emoji"]}`")

        elif command.lower() == "message": # Change or display the message
            role_config = self.get_role_config(role)
            if role_config is None:
                await log.failure(ctx, f"Role is not configured yet.")
                return
            
            if args is None: # Display current notif channel if no argument provided
                await log.client(ctx, f"Message for `{role.name}` ({role.id}) is set to {role_config["message"]}")
            else:
                log.info(f"Try to set message's role `{role.name}` ({role.id}) to {args}.")
                role_config["message"] = args
                await log.success(ctx, f"Message for `{role.name}` ({role.id}) successfully set to: `{role_config["message"]}`")
        
        elif command.lower() == "cooldown": # Change or display the cooldown
            role_config = self.get_role_config(role)
            if role_config is None:
                await log.failure(ctx, f"Role is not configured yet.")
                return
            
            if args is None: # Display current notif channel if no argument provided
                await log.client(ctx, f"Cooldown for `{role.name}` ({role.id}) is set to {role_config["cooldown"]}")
            else:
                try:
                    log.info(f"Try to set cooldown's role `{role.name}` ({role.id}) to {args}.")
                    value: int = int(args)
                    role_config["cooldown"] = value
                    await log.success(ctx, f"Cooldown for `{role.name}` ({role.id}) successfully set to: `{role_config["cooldown"]}`")
                except Exception as e:
                    await log.failure(ctx, f"Failed to set cooldown for `{role.name}` ({role.id}): `{e}`")

        else: # Default case when command argument is not listed above
            await log.failure(ctx, f"Unkown command `{command}`.")

    ####                             ####
    #       Periodic Scan Commands      #
    ####                             ####
        
    # Attempt to send a message to all members with a specific role
    async def fetch_roles(self, guildCtx: discord.Guild = None):
        for guild in self.bot.guilds:
            if (guildCtx is not None and guild != guildCtx):
                continue
            
            log.info(f"Connected to {guild.name} ({guild.id}) ({guild.member_count} members)")
            for role_to_detect in self.roles_detection:
                if not role_to_detect["enabled"]:
                    continue

                role: discord.Role = guild.get_role(role_to_detect["id"])
                if role is None:
                    continue

                log.info(f'- Members with the role {role.name} ({len(role.members)}):')
                
                channel = self.bot.get_channel(role_to_detect["channel_notif"])
                for member in role.members:
                    log.info(f"  - {member.name} ({member.id})")
                    sent = await self.send_role_message(role.id, guild, member, channel, role_to_detect["message"], forceResendDelay = role_to_detect.get("cooldown") or 60)
                    if sent:
                        await asyncio.sleep(1)

    async def enable_scan(self, ctx: commands.Context | discord.Interaction, enable: bool):
        log.info(f"{'En' if enable else 'Dis'}abling periodic scan...")
        try:
            self.periodic_scan_enabled = enable
            self.config["periodic_scan_enabled"] = enable
            if enable:
                self.start_periodic_scan()
            else:
                self.stop_periodic_scan()
            await log.success(ctx, f"Periodic scan successfully {'en' if enable else 'dis'}abled.")
        except Exception as e:
            await log.failure(ctx, f"Error when changing scan enable state: {e}")

    @commands.command()
    @predicate.admin_only()
    async def scan(self, ctx: commands.Context, command: str = None, *args: str):
        log.info(f"Nb args {len(args)} | args: {args}")
        await ctx.message.delete()

        if command is None:
            log.info(f"Scan current guild roles")
            await self.fetch_roles(ctx.guild)

        elif command.lower() == "all":
            log.info(f"Scan all roles")
            await self.fetch_roles()

        elif command.lower() == "enable":
            enable = True
            if args is not None:
                try:
                    enable = await commands.run_converters(ctx, bool, args[0], {})
                except Exception as e:
                    await log.failure(ctx, f"Failed to get boolean argument: {e}")
                    return
            await self.enable_scan(ctx, enable)

        elif command.lower() == "disable": # Shortcut for `enable off`
                await self.enable_scan(ctx, False)

        elif command.lower() == "interval":
            if len(args) > 0:
                try:
                    new_interval: int = int(args[0])
                    log.info(f"Set scan interval to '{new_interval}'")
                    self.periodic_scan.change_interval(minutes=new_interval)
                    self.config["periodic_scan_interval"] = new_interval
                    await log.success(ctx, f"Periodic scan interval successfully set to {new_interval}.")
                except Exception as e:
                    await log.failure(ctx, f"Error when trying to change scan interval: {e}")
            else:
                log.info(f"Display current scan interval")
                await log.client(ctx, f"Current scan interval is set to {int(self.periodic_scan.minutes)}")
        
        else:
            await log.client(ctx, f"Unkown command {command}.\nAvailable commands:\n- `enable [on/off]`\n- `disable` (equivalent to `enable off`)\n- `interval [<value>]`\n- `all`\n- no command (scan current server)", delete_after=20)

    ####                              ####
    #           Misc Commands            #
    ####                              ####

    # Test command to see if the BAM module is working
    @commands.command()
    async def bam(self, ctx):
        await ctx.message.delete()
        await ctx.send("BAM!", delete_after=10)

    # Delete all tracked messages
    @commands.command(aliases=["ctm"])
    @predicate.admin_only()
    async def clearTrackedMessages(self, ctx: commands.Context):
        await ctx.message.delete()

        count: int = len(self.msg_tracked)
        log.info(f"Cleaning up {count} tracked messages...")

        for key, msgData in self.msg_tracked.items():
            log.info(f"Trying to delete message {key}")
            for msgDatum in msgData:
                msg = await self.get_message(msgDatum['channel'], msgDatum['id'])
                if msg is not None:
                    try:
                        await msg.delete()
                    except Exception as e:
                        log.error(f"Error deleting message {key}: {e}")

        self.msg_tracked.clear()
        log.info("Cleanup complete.")
        await log.success(ctx, f"{count} tracked message sucessfully cleared.")

    @commands.command(aliases=["stm"])
    @predicate.admin_only()
    async def showTrackedMessages(self, ctx: commands.Context):
        await ctx.message.delete()
        log.info("Displaying tracked messages.")
        msg_list = "Tracked messages:\n"
        for key, msgData in self.msg_tracked.items():
            for msgDatum in msgData:
                try:
                    guild = self.bot.get_guild(msgDatum["guild"]) or await self.bot.fetch_guild(msgDatum["guild"])
                    channel = guild.get_channel(msgDatum["channel"]) or await guild.fetch_channel(msgDatum["channel"])
                    msg = await self.get_message(channel.id, msgDatum["id"])
                    msg_list += f"- Message `{msg.id}` in channel `{channel.name}` in guild `{guild.name}`\n"
                except Exception as e:
                    log.error(f"Failed to retrieve message {key}: {e}")
                    msg_list += f"- Message `{msgDatum['id']}` in channel `{msgDatum['channel']}` in guild `{msgDatum['guild']}` (deleted)\n"
        msg_list += f"Total tracked messages: {len(self.msg_tracked)}"
        
        await ctx.send(msg_list, delete_after=20)

    @commands.command()
    @predicate.admin_only()
    async def flush(self, ctx: commands.Context):
        await ctx.message.delete()
        log.info("Flush.")
        try:
            self.save_tracked_messages()
            self.config["roles"] = self.roles_detection
            filehelper.saveConfig(module = "bam", data = self.config)
        except Exception as e:
            log.failure(ctx, f"Failed to flush: {e}")
        await log.success(ctx, "Flushed.")
