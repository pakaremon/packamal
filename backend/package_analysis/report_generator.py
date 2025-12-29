import json
import re
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from .src.yara.yara_manager import YaraRuleManager
from django.conf import settings


def extract_evidence(match, data):
    import string

    def is_printable(s):
        return all(c in string.printable for c in s)

    evidences = []
    for string_match in match.strings:
        instances = string_match.instances
        for instance in instances[:5]:
            offset = instance.offset
            matched_length = instance.matched_length
            evidence = data[offset : offset + matched_length]
            if is_printable(evidence):
                if isinstance(evidence, bytes):
                    evidence = evidence.decode("utf-8")
                evidences.append(evidence)
    return list(set(evidences))


def generate_rule_url(src: str, rule: str) -> str:
    parts = src.split("@")
    folder_name = parts[0]
    file_name = parts[1]
    base_url = getattr(
        settings,
        "YARA_RULES_REPO_URL",
        "https://github.com/pakaremon/rust-mal/tree/master/web/package-analysis-web/package_analysis/src/yara/rules",
    )
    return f"{base_url}/{folder_name}/{file_name}.yar"


class Report:
    @staticmethod
    def generate_report(json_data):
        commands = []
        domains = []
        system_calls = []

        install_phase = json_data.get("Analysis", {}).get("install", {})

        for command in install_phase.get("Commands", []) or []:
            if command is not None:
                cmd = command.get("Command")
                if cmd:
                    if isinstance(cmd, list):
                        cmd = " ".join(cmd)
                    commands.append({"command": cmd, "rules": []})

        for dns in install_phase.get("DNS", []) or []:
            if dns is not None:
                for query in dns.get("Queries", []):
                    hostname = query.get("Hostname")
                    if hostname:
                        domains.append({"domain": hostname, "rules": []})

        pattern = re.compile(r"^Enter:\s*(.*)")
        for syscall in install_phase.get("Syscalls", []):
            if syscall is not None:
                match = pattern.match(syscall)
                if match:
                    syscall_name = match.group(1)
                    system_calls.append({"system_call": syscall_name, "rules": []})

        execution_phase = json_data.get("Analysis", {}).get("execute", {})
        if not execution_phase:
            execution_phase = json_data.get("Analysis", {}).get("import", {})

        for command in execution_phase.get("Commands", []) or []:
            if command is not None:
                cmd = command.get("Command")
                if cmd:
                    if isinstance(cmd, list):
                        cmd = " ".join(cmd)
                    commands.append({"command": cmd, "rules": []})

        for dns in execution_phase.get("DNS") or []:
            if dns is not None:
                for query in dns.get("Queries", []):
                    hostname = query.get("Hostname")
                    if hostname:
                        domains.append({"domain": hostname, "rules": []})

        for syscall in execution_phase.get("Syscalls", []):
            if syscall is not None:
                match = pattern.match(syscall)
                if match:
                    syscall_name = match.group(1)
                    system_calls.append({"system_call": syscall_name, "rules": []})

        try:
            yara_manager = YaraRuleManager.get_instance()

            command_text = "\n".join([cmd["command"] for cmd in commands])
            command_matches = yara_manager.analyze_behavior(command_text)

            domain_text = "\n".join([domain["domain"] for domain in domains])
            network_matches = yara_manager.analyze_behavior(domain_text)

            syscall_text = "\n".join(
                [syscall["system_call"] for syscall in system_calls]
            )
            syscall_matches = yara_manager.analyze_behavior(syscall_text)

            files_read = install_phase.get("files", {}).get("read", []) or []
            files_write = install_phase.get("files", {}).get("write", []) or []
            files_delete = install_phase.get("files", {}).get("delete", []) or []
            exec_read = execution_phase.get("files", {}).get("read", []) or []
            exec_write = execution_phase.get("files", {}).get("write", []) or []
            exec_delete = execution_phase.get("files", {}).get("delete", []) or []

            all_files = (
                files_read
                + exec_read
                + files_write
                + exec_write
                + files_delete
                + exec_delete
            )
            files_text = "\n".join(all_files)
            files_matches = yara_manager.analyze_behavior(files_text)

            for match in command_matches:
                rule = {
                    "name": match.rule,
                    "description": match.meta["description"],
                    "severity": "high",
                    "strings": [str(s) for s in match.strings],
                    "evidence": extract_evidence(match, command_text),
                    "url": generate_rule_url(match.namespace, match.rule),
                }
                for cmd in commands:
                    if any(str(s) in cmd["command"] for s in match.strings):
                        cmd["rules"].append(rule)

            for match in network_matches:
                rule = {
                    "name": match.rule,
                    "description": match.meta["description"],
                    "severity": "high",
                    "strings": [str(s) for s in match.strings],
                    "evidence": extract_evidence(match, domain_text),
                    "url": generate_rule_url(match.namespace, match.rule),
                }
                for domain in domains:
                    if any(str(s) in domain["domain"] for s in match.strings):
                        domain["rules"].append(rule)

            for match in syscall_matches:
                rule = {
                    "name": match.rule,
                    "description": match.meta["description"],
                    "severity": "high",
                    "strings": [str(s) for s in match.strings],
                    "evidence": extract_evidence(match, syscall_text),
                    "url": generate_rule_url(match.namespace, match.rule),
                }
                for syscall in system_calls:
                    if any(str(s) in syscall["system_call"] for s in match.strings):
                        syscall["rules"].append(rule)

            # Files Yara matches captured but not yet attached; kept for parity with upstream.
        except Exception as e:
            print(f"Yara analysis error: {e}")

        return {"commands": commands, "domains": domains, "system_calls": system_calls}

