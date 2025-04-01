# Bot Anti-Mineur (BAM)

Discord bot used to warn underage members to leave a discord server.

Can also be used to message anyone with a specific role.

## Commands

command | description
--- | ---
`bam` | `BAM!`
`listRoles` | List all tracked roles
`enableRole <id\|@role> [<true\|false>]` | Enable or disable the messages for a role.
`trackRole <role id\|@> <msg channel id\|@> <message>` | Add a new role configuration
`untrackRole <role id\|@>` | Remove a role configuration
`scanRoles` | Fetch all users of tracked roles in the server the command is called, and send them a message if possible
`setRoleCooldown <role id\|@> <value>` | Set the minimum amount of time in minutes before triggering a new message for the same member
`setRoleMessage <role id\|@> <msg>` | Change the message sent for a tracked role
`showRoleConfig <role id\|@>` | Display the configuration for a tracked role
`roleInfo <role id\|@>` | Display information for a specific role
`clearTrackedMessages` | Delete all tracked messages if possible (alias `ctm`)
`showTrackedMessages` | List all tracked messages (alias `stm`)
`flush` | Save tracked messages and config in files

## Limitations

Currently large servers will not work properly as all members are not cached.  
Thus new members are not tracked properly when updating their roles. The command `scanRoles` or reloading the extension can be used periodically to scan members of a certain roles and trigger the messages.  
A periodic task may be added in the future to overcome this limitation.
