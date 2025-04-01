import asyncio
import datetime
import time
import typing
import discord
from discord.ext import commands
import json
import os

class BAM(commands.Cog):
    def __init__(self, bot):
        print(f"[INFO] BAM module init...")
        self.bot = bot
        self.msg_tracked: dict[str, any] = {}
        self.config_path = "config/config.bam.json"
        self.tracked_msg_save_path = "save/tracked_messages.bam.json"
        #self.periodic_scan = None
        try:
            with open(self.config_path, "r") as file:
                self.config = json.load(file)
                self.roles_detection = self.config["roles"]
                self.tracked_msg_save_path = self.config["save_path"]["tracked_messages"]
        except FileNotFoundError:
            print(f"Config file not found. Using default values.")

    def save_config(self, config):
        with open(self.config_path, "w+") as file:
            json.dump(config, file, indent=4)

    def load_tracked_messages(self):
        # Create the directory if it doesn't exist
        if not os.path.exists("save"):
            os.makedirs("save")
        if os.path.exists(self.tracked_msg_save_path):
            with open(self.tracked_msg_save_path, "r") as file:
                self.msg_tracked = json.load(file)
                print(f"Tracked messages loaded from {self.tracked_msg_save_path}: {self.msg_tracked}")

    def save_tracked_messages(self):
        with open(self.tracked_msg_save_path, "w+") as file:
            json.dump(self.msg_tracked, file, indent=4)
            print(f"Tracked messages saved to {self.tracked_msg_save_path}: {self.msg_tracked}")

    # Cog startup
    async def cog_load(self):
        print(f"[INFO] BAM module startup!")
        self.load_tracked_messages()
        await self.fetch_roles()
    
    # Cog cleanup
    async def cog_unload(self):
        print(f"[INFO] BAM module cleanup!")
        self.save_tracked_messages()
        self.save_config(self.config)

    # Try to retrieve a message from a channel
    async def get_message(self, channel_id: int, message_id: int) -> typing.Optional[discord.Message]:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            print(f"Channel not found: {channel_id}")
            return None

        message = None
        try:
            message = await channel.fetch_message(message_id)
            print("Message found!")
        except discord.NotFound:
            print("Message not found")
        except discord.Forbidden:
            print("Not allowed to access this channel")
        except Exception as e:
            print(f"Failed to get message: {e}")

        return message
    
    # Attempt to send a message to all members with a specific role
    async def fetch_roles(self, guildCtx: discord.Guild = None):
        for guild in self.bot.guilds:
            if (guildCtx is not None and guild != guildCtx):
                continue
            
            print(f"Connected to {guild.name} ({guild.id}) ({guild.member_count} members)")
            for role_to_detect in self.roles_detection:
                if not role_to_detect["enabled"]:
                    continue

                role = guild.get_role(role_to_detect["id"])
                if role is None:
                    continue

                await role.fetch_members(subscribe=True)
                print(f'- Members with the role {role.name} ({len(role.members)}):')
                
                channel = self.bot.get_channel(role_to_detect["channel_notif"])
                for member in role.members:
                    print(f"  - {member.name} ({member.id})")
                    sent = await self.send_role_message(role.id, guild, member, channel, role_to_detect["message"], forceResendDelay = role_to_detect["forceResendAfterMinutes"])
                    if sent:
                        await asyncio.sleep(1)

    # Send a message in a channel and track this message for later deletion
    # returns True when the message has been sent, false otherwise
    async def send_role_message(self, role_id:int, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, message: str, resend: bool = False, forceResendDelay: int = 60, replyParent: discord.Message = None) -> bool:
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
                    print(f"Message already sent to {member.name} ({member.id}) in {guild.name} ({guild.id}), (elapsed minutes since last message: {elapsed_minutes}).")
                    if elapsed_minutes > forceResendDelay:
                        resend = True
                        print(f"Forcing resend (>{forceResendDelay} minutes).")
                    else:
                        print(f"Not resending message (<{forceResendDelay} minutes).")
                except Exception as e:
                    print(f"❌ Failed to retrieve tracked message timestamp: {e}")
                    
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
        
            print(f"Message tracked: {key}")
            return True
        except Exception as e:
            print(f"❌ Failed to send message: {e}")
        return False

    async def delete_role_message(self, key: str):
        for msgData in self.msg_tracked.get(key):
            try:
                msg = await self.get_message(msgData["channel"], msgData["id"])
                await msg.delete()
                del self.msg_tracked[key]
                print(f"Message untracked {key}")
            except Exception as e:
                print(f"❌ Failed to delete message: {e}")

    # Test command to see if the BAM module is working
    @commands.command()
    async def bam(self, ctx):
        await ctx.message.delete()
        await ctx.send("BAM!", delete_after=5)

    # Just log for now when a member joins the server
    @commands.Cog.listener()
    async def on_member_join(self, member):
        print(f"Member {member.name} ({member.id}) joined {member.guild.name}")

    # Detect when a member updates their roles
    # and send a message in the specified channel if the role is detected
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        before_roles = set(role.id for role in before.roles)
        after_roles = set(role.id for role in after.roles)
        new_roles = after_roles - before_roles

        print(f"Member {after.name} ({after.id}) updated in {after.guild.name}. New roles: {new_roles}")

        await self.send_message(after, after.guild)

    # Delete the tracked message when the member leaves the server
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f"Member {member.name} ({member.id}) removed from {member.guild.name} ({member.guild.id})")
        key = f"{member.guild.id}-{member.id}"
        await self.delete_role_message(key)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not isinstance(message.author, discord.Member):
            return
        
        for role_to_detect in self.roles_detection:
            if not role_to_detect["enabled"]:
                continue
            if role_to_detect["id"] in [role.id for role in message.author.roles]:
                print(f"React to message with emoji {role_to_detect['emoji']}")
                await message.add_reaction(role_to_detect["emoji"])
                break

        await self.send_message(message.author, message.guild, replyParent=message)


    # Send tracked role message
    async def send_message(self, member: discord.Member, guild: discord.Guild, replyParent: discord.Message = None):
        for role_to_detect in self.roles_detection:
            if not role_to_detect["enabled"]:
                continue
            if role_to_detect["id"] in [role.id for role in member.roles]:
                print(f"Detected role {role_to_detect['id']} for {member.name} ({member.id}) in {member.name}")
                channel = self.bot.get_channel(role_to_detect["channel_notif"])
                if not channel:
                    print("❌ No channel to send the message.")
                    continue
                await self.send_role_message(role_to_detect["id"], guild, member, channel, role_to_detect["message"], replyParent=replyParent)


    # Delete all tracked messages
    @commands.command(aliases=["ctm"])
    async def clearTrackedMessages(self, ctx):
        await ctx.message.delete()

        print(f"Cleaning up {len(self.msg_tracked)} tracked messages...")

        for key, msgData in self.msg_tracked.items():
            print(f"Trying to delete message {key}")
            for msgDatum in msgData:
                msg = await self.get_message(msgDatum['channel'], msgDatum['id'])
                if msg is not None:
                    try:
                        await msg.delete()
                    except Exception as e:
                        print(f"Error deleting message {key}: {e}")

        self.msg_tracked.clear()
        print("Cleanup complete.")


    @commands.command()
    async def listRoles(self, ctx):
        await ctx.message.delete()
        print("Displaying tracked roles.")

        role_list = "Tracked roles:\n"
        for role in self.roles_detection:
            role_list += f"- Role {role['id']} in channel {role['channel_notif']} (enabled: {role['enabled']})\n"
        
        await ctx.send(role_list, delete_after=20)
        print("End")

    @commands.command()
    async def enableRole(self, ctx, role: int | discord.Role, value: bool = True):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)

        for role in self.roles_detection:
            if role["id"] == role_id:
                role["enabled"] = value
                print(f"{'En' if value else 'Dis'}abling role {role_id}")
                await ctx.send(f"Role {role_id} tracking status: {':white_check_mark:' if value else ':x:'}", delete_after=5)
                return
        await ctx.send(f"Role {role_id} not configured yet.", delete_after=5)

    @commands.command()
    async def trackRole(self, ctx, role: int | discord.Role, channel: int | discord.TextChannel, message: str):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
            
        if isinstance(channel, discord.TextChannel):
            channel_id = channel.id
        else:
            channel_id = int(channel)

        print(f"Try to track role {role_id}. Notification in channel: {channel_id}. Message: {message}")
        for role in self.roles_detection:
            if role["id"] == role_id:
                await ctx.send(f":x: Role {role_id} is already configured.", delete_after=5)
                return
        # Add the new role to the list
        new_role = {
            "enabled": True,
            "id": role_id,
            "channel_notif": channel_id,
            "emoji": None,
            "forceResendAfterMinutes": 60,
            "message": message
        }
        self.roles_detection.append(new_role)
        await ctx.send(f":white_check_mark: Role {role_id} now configured.", delete_after=5)

    @commands.command()
    async def untrackRole(self, ctx, role: int | discord.Role):
        await ctx.message.delete()

        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)

        print(f"Try to untrack role {role_id}.")
        for i, tracked_role in enumerate(self.roles_detection):
            if tracked_role["id"] == role_id:
                del self.roles_detection[i]
                await ctx.send(f":white_check_mark: Role {role_id} now untracked.", delete_after=5)
                return
        await ctx.send(f":x: Role {role_id} not configured yet.", delete_after=5)

    @commands.command(aliases=["scan"])
    async def scanRoles(self, ctx):
        await ctx.message.delete()
        await self.fetch_roles(ctx.guild)
        
    @commands.command()
    async def setRoleCooldown(self, ctx, role: int | discord.Role, cooldown: int):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        print(f"Try to set cooldown for role {role_id} to {cooldown} minutes.")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["forceResendAfterMinutes"] = cooldown
                await ctx.send(f":white_check_mark: Role {role_id} cooldown set to {cooldown} minutes.", delete_after=5)
                return
        await ctx.send(f":x: Role {role_id} not configured yet.", delete_after=5)

    @commands.command()
    async def setRoleMessage(self, ctx, role: int | discord.Role, message: str):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        print(f"Try to set message for role {role_id} to '{message}'")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["message"] = message
                await ctx.send(f":white_check_mark: Role {role_id} message successfully set.", delete_after=5)
                return
        await ctx.send(f":x: Role {role_id} not configured yet.", delete_after=5)

    @commands.command()
    async def setRoleEmoji(self, ctx, role: int | discord.Role, emoji: str = None):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_id = role.id
        else:
            role_id = int(role)
        print(f"Try to set emoji for role {role_id} to '{emoji}'")
        for tracked_role in self.roles_detection:
            if tracked_role["id"] == role_id:
                tracked_role["emoji"] = emoji
                await ctx.send(f":white_check_mark: Role {role_id} emoji successfully set.", delete_after=5)
                return
        await ctx.send(f":x: Role {role_id} not configured yet.", delete_after=5)

    @commands.command()
    async def showRoleConfig(self, ctx, role: int | discord.Role):
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
**Cooldown**: {tracked_role['forceResendAfterMinutes']}\n\
**Message**: {tracked_role['message']}", delete_after=20)
                return
        await ctx.send(f":x: Role {role_id} not configured yet.", delete_after=5)

    @commands.command()
    async def roleInfo(self, ctx, role: int | discord.Role):
        await ctx.message.delete()
        if isinstance(role, discord.Role):
            role_inst = role
        else:
            role_inst = ctx.guild.get_role(int(role)) or await ctx.guild.fetch_role(int(role))
        
        if role_inst is None:
            await ctx.send(f":x: Role {role} not found.", delete_after=5)
            return
        
        print(f"Display role informations for {role_inst.name} ({role_inst.id})")

        try:
            await ctx.send(f"**Role {role_inst.name}**\n\
**ID**: {role_inst.id}\n\
**Creation**: {role_inst.created_at.strftime('%a, %d %b %Y %I:%M %p')}\n\
**Position**: {role_inst.position}\n\
**Mentionable**: {role_inst.mentionable}", delete_after=20)
        except Exception as e:
            print(f"❌ Failed to retrieve role information: {e}")
            await ctx.send(f":x: Failed to retrieve role information: {e}", delete_after=5)

    @commands.command(aliases=["stm"])
    async def showTrackedMessages(self, ctx):
        await ctx.message.delete()
        print("Displaying tracked messages.")
        msg_list = "Tracked messages:\n"
        for key, msgData in self.msg_tracked.items():
            for msgDatum in msgData:
                try:
                    guild = self.bot.get_guild(msgDatum["guild"]) or await self.bot.fetch_guild(msgDatum["guild"])
                    channel = guild.get_channel(msgDatum["channel"]) or await guild.fetch_channel(msgDatum["channel"])
                    msg = await self.get_message(channel.id, msgDatum["id"])
                    msg_list += f"- Message `{msg.id}` in channel `{channel.name}` in guild `{guild.name}`\n"
                except Exception as e:
                    print(f"❌ Failed to retrieve message {key}: {e}")
                    msg_list += f"- Message `{msgDatum['id']}` in channel `{msgDatum['channel']}` in guild `{msgDatum['guild']}` (deleted)\n"
        msg_list += f"Total tracked messages: {len(self.msg_tracked)}"
        
        await ctx.send(msg_list)

    @commands.command()
    async def flush(self, ctx):
        await ctx.message.delete()
        self.save_tracked_messages()
        self.save_config(self.config)

async def setup(bot):
    await bot.add_cog(BAM(bot))
    print("[INFO] BAM extension loaded")

async def teardown(bot):
    await bot.remove_cog("BAM")
    print("[INFO] BAM extension unloaded")