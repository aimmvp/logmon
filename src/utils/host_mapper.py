HOST_MAP = {
    'i-023c16c7968372b38': 'SSO_01',
    'i-00dd30849ccfba93a': 'SSO_02',
    'i-06d8bd0429c15d38c': 'SSO_03',
    'i-0a2328f9d6500e6c4': 'SSO_04',
}

def map_host(host: str) -> str:
    return HOST_MAP.get(host, host)