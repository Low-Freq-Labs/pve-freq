#!/bin/bash
# =============================================================================
# PVE FREQ v2.0.0 — Bash Tab Completion
#
# Install:
#   cp completions/freq.bash /etc/bash_completion.d/freq
#   or: echo 'source /opt/pve-freq/completions/freq.bash' >> ~/.bashrc
#
# Provides completions for:
#   freq <command> <subcommand> [--flags]
# =============================================================================

_freq_completions() {
    local cur prev words cword
    _init_completion || return

    # Top-level commands
    local commands="
        create clone resize destroy list snapshot import vm-status change-id
        dashboard status exec run-on info diagnose docker ssh log history
        hosts discover groups setup onboard
        new-user passwd users roles keys promote demote
        vm-overview vmconfig migrate rescue
        pfsense truenas switch idrac opnsense
        health audit doctor watch vault media
        harden provision images templates backup vpn wazuh notify
        mount mounts registry configure serial journal zfs pdm checkpoint
        check fix diff policies engine
        learn risk creds credentials
        init version help
    "

    # Engine policies (cached per session)
    local policies="ssh-hardening ntp-sync rpcbind-block docker-security nfs-security auto-updates"

    # Global flags
    local global_flags="--dry-run --json --yes --debug --help"

    case "$cword" in
        1)
            # First argument: complete commands
            COMPREPLY=($(compgen -W "$commands" -- "$cur"))
            ;;
        2)
            # Second argument: depends on command
            case "$prev" in
                check|fix|diff)
                    COMPREPLY=($(compgen -W "$policies" -- "$cur"))
                    ;;
                hosts)
                    COMPREPLY=($(compgen -W "add remove list show" -- "$cur"))
                    ;;
                vm|snapshot|snap)
                    COMPREPLY=($(compgen -W "list create delete restore" -- "$cur"))
                    ;;
                harden)
                    COMPREPLY=($(compgen -W "check fix status" -- "$cur"))
                    ;;
                backup)
                    COMPREPLY=($(compgen -W "snapshot diff list restore" -- "$cur"))
                    ;;
                vault)
                    COMPREPLY=($(compgen -W "list get set delete init" -- "$cur"))
                    ;;
                watch)
                    COMPREPLY=($(compgen -W "start stop status" -- "$cur"))
                    ;;
                vpn)
                    COMPREPLY=($(compgen -W "status peers" -- "$cur"))
                    ;;
                mount|mounts)
                    COMPREPLY=($(compgen -W "status verify repair" -- "$cur"))
                    ;;
                docker)
                    COMPREPLY=($(compgen -W "ps images stats" -- "$cur"))
                    ;;
                pfsense|pf)
                    COMPREPLY=($(compgen -W "rules nat aliases services logs states probe dhcp dns gateway backup" -- "$cur"))
                    ;;
                truenas|tn)
                    COMPREPLY=($(compgen -W "pools datasets shares alerts snapshots services replication smart network disks system" -- "$cur"))
                    ;;
                switch|sw)
                    COMPREPLY=($(compgen -W "ports vlans status mac arp trunk show cdp version poe save config" -- "$cur"))
                    ;;
                idrac)
                    COMPREPLY=($(compgen -W "info sensors power bios sel network" -- "$cur"))
                    ;;
                engine)
                    COMPREPLY=($(compgen -W "check fix diff policies status" -- "$cur"))
                    ;;
                learn)
                    COMPREPLY=()  # Free-text search
                    ;;
                risk)
                    COMPREPLY=($(compgen -W "pfsense truenas pve01 pve02 pve03 switch" -- "$cur"))
                    ;;
                creds|credentials)
                    COMPREPLY=($(compgen -W "status audit rotate keys help" -- "$cur"))
                    ;;
                clone)
                    # Complete with template VMIDs
                    COMPREPLY=($(compgen -W "9000 9001 9002 9003 9004 9005 9008 9009 9010 9011" -- "$cur"))
                    ;;
                destroy|resize|vmconfig|rescue|migrate)
                    # Complete with running VM IDs (could be dynamic but keep it fast)
                    COMPREPLY=()
                    ;;
                *)
                    COMPREPLY=($(compgen -W "$global_flags" -- "$cur"))
                    ;;
            esac
            ;;
        *)
            # Third+ arguments: flags
            case "${words[1]}" in
                check|fix|diff)
                    COMPREPLY=($(compgen -W "--hosts --max-parallel --dry-run --json --verbose --connect-timeout --command-timeout --password" -- "$cur"))
                    ;;
                clone)
                    COMPREPLY=($(compgen -W "--vmid --node --ip --linked --dry-run --yes" -- "$cur"))
                    ;;
                create)
                    COMPREPLY=($(compgen -W "--vmid --name --node --cores --memory --disk --template --ip --dry-run --yes" -- "$cur"))
                    ;;
                destroy)
                    COMPREPLY=($(compgen -W "--yes --force --purge --dry-run" -- "$cur"))
                    ;;
                resize)
                    COMPREPLY=($(compgen -W "--cores --memory --disk --yes --force --dry-run" -- "$cur"))
                    ;;
                snapshot)
                    COMPREPLY=($(compgen -W "--name --description --dry-run --yes" -- "$cur"))
                    ;;
                exec|run-on)
                    COMPREPLY=($(compgen -W "--parallel --timeout --group --type" -- "$cur"))
                    ;;
                audit)
                    COMPREPLY=($(compgen -W "--all --brief --json --category" -- "$cur"))
                    ;;
                *)
                    COMPREPLY=($(compgen -W "$global_flags" -- "$cur"))
                    ;;
            esac
            ;;
    esac
}

complete -F _freq_completions freq
