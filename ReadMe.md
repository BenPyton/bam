# Bot Anti-Mineur (BAM)

Discord bot extension used to warn underage members to leave a discord server.

Can also be used to message anyone with a specific role.

## Installation

### Installing in a Dismob

Download (or add it as a git submodule) this repository into your Dismob project.  
You must place it in `./plugins/bam/` in order to be able to use `load bam` command of Dismob.

```
Dismob root directory
|- main.py
|- ...
|- plugins
   |- bam <- This is the git repo download or clone
      |- main.py
```

### Installing in another bot

> [!WARNING]
> This extension is meant to be used within a [Dismob](https://github.com/BenPyton/Dismob) bot!  
> Some imports comes from there (e.g. `log`, `predicates` and `filehelper`)  
> If you want to use it outside of a Dismob, you'll have to grab those required files from the Dismob repo.

Place it in a subfolder of your project.  
For the example below, I'll use the same folder structure as for Dismob (so I place it in `./plugins/bam/` subfolder)

Then you can either load it as an extension (allowing hot-reload), or mount the cog on your bot (no hot-reload):

```py
# Use it as an extension to load/unload at runtime
# This will search for the main.py placed in ./plugins/bam directory
await bot.load_extension("plugins.bam.main")
await bot.reload_extension("plugins.bam.main")
await bot.unload_extension("plugins.bam.main")

# You can also use it as a Cog but this won't allow hot-reload
await bot.add_cog(BAM(bot))
await bot.remove_cog("BAM")
```

## Commands

### Role Detection Configuration Commands

command | description
--- | ---
`role` | List all configured roles.
`role <@role>` | Display information about the role and configuration details if any.
`role <@role> enable [on\|off]` | Enable or disable the role configuration. Default to `on` if no argument passed.
`role <@role> disable` | Shortcut for `role <@role> enable off`.
`role <@role> track [key=val]...` | Create a configuration for the role. Takes optional arguments as the form `key=value` to set directly the data. (see the role commands below to know what arguments can be passed this way)
`role <@role> untrack` | Delete the configuration for the specified role.
`role <@role> channel [<#channel>]` | Set the role's configuration channel to send message. Display the currently set channel if no argument passed.
`role <@role> emoji [<value>]` | Set the role's configuration emoji for message reactions. Display the currently set emoji if no argument passed.
`role <@role> message [<value>]` | Set the role's configuration message to send. Display the currently set message if no argument passed.
`role <@role> cooldown [<value>]` | Set the role's configuration cooldown (in minute) before resending a message to the same user. Display the currently set cooldown if no argument passed.

### Periodic Scan Commands

command | description
--- | ---
`scan` | Fetch all users of tracked roles in the server the command is called, and send them a message if possible.
`scan all` | Same as `scan` but for all servers.
`scan enable [on\|off]` | Enable or disable the periodic scan. If no argument passed, assumes `on`.
`scan disable` | Shortcut for `scan enable off`
`scan interval [<value>]` | Set the periodic scan interval (in minutes). If no argument passed, display the current value.

### Misc Commands

command | description
--- | ---
`bam` | `BAM!`
`clearTrackedMessages` | Delete all tracked messages if possible (alias `ctm`)
`showTrackedMessages` | List all tracked messages (alias `stm`)
`flush` | Save tracked messages and config in files

### Command Syntax

This part is to help you understand the command syntax I used in the above tables.

Text placed inside `<>` is an argument to be replaced by the appropriate values.  
Text placed inside `[]` is optional and may not be provided.  
The `|` is used to mark alternative values.  
The `...` means that last may be repeated any times.

## Limitations

Currently large servers will not work properly as all members are not cached.  
Thus new members are not tracked properly when updating their roles. The command `scanRoles` or reloading the extension can be used periodically to scan members of a certain roles and trigger the messages.  
A periodic task may be added in the future to overcome this limitation.
