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
        results = {
            'install': {
                'num_files': 0,
                'num_commands': 0,
                'num_network_connections': 0,
                'num_system_calls': 0,
                'files': {
                    'read': [],
                    'write': [],
                    'delete': [],
                },
                'dns': [],
                'ips': [],
                'commands': [],
                'syscalls': []
            },
            'execute': {
                'num_files': 0,
                'num_commands': 0,
                'num_network_connections': 0,
                'num_system_calls': 0,
                'files': {
                    'read': [],
                    'write': [],
                    'delete': [],
                },
                'dns': [],
                'ips': [],
                'commands': [],
                'syscalls': []
            }
        }
        # generate a report based on the data
        # for now, just print the data to the console
        install_phase = json_data.get('Analysis', {}).get('install', {})

        results['install']['num_files'] = len(install_phase.get('Files') or [])
        results['install']['num_commands'] = len(install_phase.get('Commands') or [])
        results['install']['num_network_connections'] = len(install_phase.get('Sockets') or [])
        # for number of system calls divide by 2 because the system calls are 'enter' and 'exit' 
        # so we need to divide by 2 to get the actual number of system calls
        results['install']['num_system_calls'] = len(install_phase.get('Syscalls') or []) // 2

        for file in install_phase.get('Files', []):
            if file.get('Read'):
                results['install']['files']['read'].append(file.get('Path'))
            if file.get('Write'):
                results['install']['files']['write'].append(file.get('Path'))
            if file.get('Delete'):
                results['install']['files']['delete'].append(file.get('Path'))

        for dns in install_phase.get('DNS', []) or []:
            if dns is not None:
                for query in dns.get('Queries', []):
                    results['install']['dns'].append(query.get('Hostname'))
        
        for socket in install_phase.get('Sockets', []) or []:
            if socket is not None:
                results['install']['ips'].append({
                    'Address': socket.get('Address'), 
                    'Port': socket.get('Port'),
                    'Hostnames': ' '.join(socket.get('Hostnames') or [])
                })
        
        for command in install_phase.get('Commands', []) or []:
            if command is not None:
                results['install']['commands'].append(command.get('Command'))

        # pattern = re.compile(r'^Enter:\s*([\w]+)')
        pattern = re.compile(r'^Enter:\s*(.*)')
        for syscall in install_phase.get('Syscalls', []):
            if syscall is not None:
                match = pattern.match(syscall)
                if match:
                    results['install']['syscalls'].append(match.group(1))

        execution_phase = json_data.get('Analysis', {}).get('execute', {})
        if not execution_phase:
            execution_phase = json_data.get('Analysis', {}).get('import', {})

        results['execute']['num_files'] = len(execution_phase.get('Files') or [])
        results['execute']['num_commands'] = len(execution_phase.get('Commands') or [])
        results['execute']['num_network_connections'] = len(execution_phase.get('Sockets') or [])
        results['execute']['num_system_calls'] = len(execution_phase.get('Syscalls') or []) // 2

        for file in execution_phase.get('Files', []):
            if file.get('Read'):
                results['execute']['files']['read'].append(file.get('Path'))
            if file.get('Write'):
                results['execute']['files']['write'].append(file.get('Path'))

        for dns in execution_phase.get('DNS') or []:
            if dns is not None:
                for query in dns.get('Queries', []):
                    results['execute']['dns'].append(query.get('Hostname'))

        for socket in execution_phase.get('Sockets', []) or []:
            if socket is not None:
                results['execute']['ips'].append({
                    'Address': socket.get('Address'), 
                    'Port': socket.get('Port'),
                    'Hostnames': ' '.join(socket.get('Hostnames') or [])
                })
        
        for command in execution_phase.get('Commands', []) or []:
            if command is not None:
                results['execute']['commands'].append(command.get('Command'))
        
        # pattern = re.compile(r'^Enter:\s*([\w]+)')
        pattern = re.compile(r'^Enter:\s*(.*)')
        for syscall in execution_phase.get('Syscalls', []):
            if syscall is not None:
                match = pattern.match(syscall)
                if match:
                    results['execute']['syscalls'].append(match.group(1))

        # Add Yara analysis
        try:
            from .src.yara.yara_manager import YaraRuleManager
            from .src.yara.yara_manager import ReportYara

            yara_manager = YaraRuleManager()
            
            commands = [' '.join(cmd) for cmd in results['install']['commands']]
            commands.extend([' '.join(cmd) for cmd in results['execute']['commands']])
            # Convert commands to string for Yara analysis
            command_text = '\n'.join([
                cmd for cmd in commands
                if isinstance(cmd, str)
            ])
            
            # Convert DNS entries to string for Yara analysis
            dns_text = '\n'.join([
                dns for dns in results['install']['dns'] + results['execute']['dns']
                if isinstance(dns, str)
            ])
            
            # Convert system calls to string for Yara analysis
            syscall_text = '\n'.join([
                syscall for syscall in results['install']['syscalls'] + results['execute']['syscalls']
                if isinstance(syscall, str)
            ])
            
            files_text = '\n'.join([
                file for file in results['install']['files']['read'] + results['execute']['files']['read'] + results['install']['files']['write'] + results['execute']['files']['write'] + results['install']['files']['delete'] + results['execute']['files']['delete']
                if isinstance(file, str)
            ])
            
            # Analyze with Yara rules
            command_matches = yara_manager.analyze_behavior(command_text)
            network_matches = yara_manager.analyze_behavior(dns_text)
            syscall_matches = yara_manager.analyze_behavior(syscall_text)
            files_matches = yara_manager.analyze_behavior(files_text)
            
            # ref: https://github.com/chainguard-dev/malcontent/blob/9ede1b235b0b21cef84ff5d1bc075b68f651401f/pkg/report/report.go#L380

            #         {
            # "category": "command",
            # "rule": "suspicious_shell",
            # "strings": ["$s1: \"curl http://x.x.x.x/m.sh\" at 0x42"],
            # "severity": "high",
            # "metadata": {
            #     "description": "Detects suspicious shell commands"
            # }
            # }
 
            # Add Yara results to report
            results['yara_analysis'] = {
                'command_matches': [{
                    'rule': match.rule,
                    'strings': [str(s) for s in match.strings],
                    'severity': match.meta['severity'],
                    'description': match.meta['description'],
                    'category': match.meta['category'],
                    'author': match.meta['author'],
                    'date': match.meta['date'],
                    'evidence': ReportYara.extract_evidence(match, command_text),
                    'url': ReportYara.generate_rule_url(match.namespace, match.rule)
                } for match in command_matches],
                'network_matches': [{
                    'rule': match.rule,
                    'strings': [str(s) for s in match.strings],
                    'severity': match.meta['severity'],
                    'description': match.meta['description'],
                    'category': match.meta['category'],
                    'author': match.meta['author'],
                    'date': match.meta['date'],
                    'evidence': ReportYara.extract_evidence(match, dns_text),
                    'url': ReportYara.generate_rule_url(match.namespace, match.rule)
                } for match in network_matches],
                'syscall_matches': [{
                    'rule': match.rule,
                    'strings': [str(s) for s in match.strings],
                    'severity': match.meta['severity'],
                    'description': match.meta['description'],
                    'category': match.meta['category'],
                    'author': match.meta['author'],
                    'date': match.meta['date'],
                    'evidence': ReportYara.extract_evidence(match, syscall_text),
                    'url': ReportYara.generate_rule_url(match.namespace, match.rule)
                } for match in syscall_matches],
                'files_matches': [{
                    'rule': match.rule,
                    'strings': [str(s) for s in match.strings],
                    'severity': match.meta['severity'],
                    'description': match.meta['description'],
                    'category': match.meta['category'],
                    'evidence': ReportYara.extract_evidence(match, files_text),
                    'url': ReportYara.generate_rule_url(match.namespace, match.rule)
                } for match in files_matches]
            }

            logger.info(results['yara_analysis'])
        except ImportError:
            # If Yara analysis is not available, continue without it
            pass
        
        return results
