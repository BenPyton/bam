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

    # Test command to see if the BAM module is working
    @commands.command()
    async def bam(self, ctx):
        await ctx.message.delete()
        await ctx.send("BAM!", delete_after=10)

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

    @commands.command()
    @predicate.admin_only()
    async def listRoles(self, ctx: commands.Context):
        await ctx.message.delete()
        log.info("Displaying tracked roles.")

        role_list = "Tracked roles:\n"
        for role in self.roles_detection:
            role_list += f"- Role {role['id']} in channel {role['channel_notif']} (enabled: {role['enabled']})\n"
        
        await ctx.send(role_list, delete_after=20)
        log.info("End")

    @commands.command()
    @predicate.admin_only()
    async def enableRole(self, ctx: commands.Context, role: int | discord.Role, value: bool = True):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)

        for role in self.roles_detection:
            if role["id"] == role_id:
                role["enabled"] = value
                log.info(f"{'En' if value else 'Dis'}abling role {role_id}")
                await ctx.send(f"Role {role_id} tracking status: {':white_check_mark:' if value else ':x:'}", delete_after=5)
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def trackRole(self, ctx: commands.Context, role: int | discord.Role, channel: int | discord.TextChannel, message: str):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
            
        if isinstance(channel, discord.TextChannel):
            channel_id = channel.id
        else:
            channel_id = int(channel)

        log.info(f"Try to track role {role_id}. Notification in channel: {channel_id}. Message: {message}")
        for role in self.roles_detection:
            if role["id"] == role_id:
                await log.failure(f"Role {role_id} is already configured.")
                return
        # Add the new role to the list
        new_role = {
            "enabled": True,
            "id": role_id,
            "channel_notif": channel_id,
            "emoji": None,
            "cooldown": 60,
            "message": message
        }
        self.roles_detection.append(new_role)
        await log.success(ctx, f"Role {role_id} now configured.")

    @commands.command()
    @predicate.admin_only()
    async def untrackRole(self, ctx: commands.Context, role: int | discord.Role):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)

        log.info(f"Try to untrack role {role_id}.")
        for i, tracked_role in enumerate(self.roles_detection):
            if tracked_role["id"] == role_id:
                del self.roles_detection[i]
                await log.success(ctx, f"Role {role_id} now untracked.")
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def setRoleCooldown(self, ctx: commands.Context, role: int | discord.Role, cooldown: int):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        log.info(f"Try to set cooldown for role {role_id} to {cooldown} minutes.")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["cooldown"] = cooldown
                await log.success(ctx, f"Role {role_id} cooldown set to {cooldown} minutes.")
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def setRoleMessage(self, ctx: commands.Context, role: int | discord.Role, message: str):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        log.info(f"Try to set message for role {role_id} to '{message}'")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["message"] = message
                await log.success(ctx, f"Role {role_id} message successfully set.")
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def setRoleEmoji(self, ctx: commands.Context, role: int | discord.Role, emoji: str = None):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        log.info(f"Try to set emoji for role {role_id} to '{emoji}'")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["emoji"] = emoji
                await log.success(ctx, f"Role {role_id} emoji successfully set.")
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def showRoleConfig(self, ctx: commands.Context, role: int | discord.Role):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                await ctx.send(f"**Role**\n\
**ID**: {role_id}\n\
**Status**: {':white_check_mark:' if tracked_role['enabled'] else ':x:'}\n\
**Notif Channel**: {tracked_role['channel_notif']}\n\
**Cooldown**: {tracked_role['cooldown']}\n\
**Message**: {tracked_role['message']}", delete_after=20)
                return
        await log.failure(ctx, f"Role {role_id} not configured yet.")

    @commands.command()
    @predicate.admin_only()
    async def roleInfo(self, ctx: commands.Context, role: int | discord.Role):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_inst = role
        else:
            role_inst = ctx.guild.get_role(int(role)) or await ctx.guild.fetch_role(int(role))
        
        if role_inst is None:
            await log.failure(f"Role {role} not found.")
            return
        
        log.info(f"Display role informations for {role_inst.name} ({role_inst.id})")

        try:
            await ctx.send(f"**Role {role_inst.name}**\n\
**ID**: {role_inst.id}\n\
**Creation**: {role_inst.created_at.strftime('%a, %d %b %Y %I:%M %p')}\n\
**Position**: {role_inst.position}\n\
**Mentionable**: {role_inst.mentionable}", delete_after=20)
        except Exception as e:
            errMsg: str = f"Failed to retrieve role information: {e}"
            log.error(errMsg)
            await log.failure(ctx, errMsg)

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
            if len(args) > 0:
                log.warning(f"args `{args[0]}` converted into bool: {args[0] == True}")
                await self.enable_scan(ctx, args[0] == True)
            else: # Assume we want to `enable on` if no argument passed
                await self.enable_scan(ctx, True)

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

