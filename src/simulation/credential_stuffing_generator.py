from pathlib import Path
from datetime import datetime, timedelta
import argparse
import random
import duckdb
import pandas as pd

# =========================================================
# PROJECT PATHS
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

ORGANIZATIONS_DIR = (
    PROJECT_ROOT / "data" / "organizations"
)

PHASE5_DIR = (
    PROJECT_ROOT / "data" / "phase5"
)

SYNTHETIC_EVENTS_DIR = (
    PHASE5_DIR / "synthetic_events"
)

METADATA_DIR = (
    PHASE5_DIR / "metadata"
)


# =========================================================
# ORGANIZATIONS
# =========================================================

ORGANIZATIONS = [
    "Org1",
    "Org2",
    "Org3",
    "Org4",
    "Org5",
]


# =========================================================
# PRIMARY PARAMETER LEVELS
# =========================================================

ROTATION_LEVELS = {
    "Low": 0.20,
    "Medium": 0.50,
    "High": 0.80,
}

ACCOUNT_REUSE_LEVELS = {
    "Low": 0.20,
    "Medium": 0.50,
    "High": 0.80,
}


# =========================================================
# SECONDARY CAMPAIGN PARAMETERS
# =========================================================

CAMPAIGN_DURATION_MINUTES = 60
NUM_CREDENTIAL_IDENTITIES = 100

MIN_ATTEMPTS_PER_ACCOUNT = 1
MAX_ATTEMPTS_PER_ACCOUNT = 3

SUCCESS_PROBABILITY = 0.05

# Small campaign used only for testing the generator
PILOT_NUM_CREDENTIAL_IDENTITIES = 10
PILOT_CAMPAIGN_START = "2020-08-01 12:00:00"


# =========================================================
# 12 CAMPAIGN SCENARIO FAMILIES
# =========================================================

SCENARIOS = {

    "CS_001": {
        "rotation_level": "Low",
        "org_spread": 1,
        "account_reuse_level": None,
    },

    "CS_002": {
        "rotation_level": "Medium",
        "org_spread": 1,
        "account_reuse_level": None,
    },

    "CS_003": {
        "rotation_level": "High",
        "org_spread": 1,
        "account_reuse_level": None,
    },

    "CS_004": {
        "rotation_level": "Low",
        "org_spread": 2,
        "account_reuse_level": "Low",
    },

    "CS_005": {
        "rotation_level": "Medium",
        "org_spread": 2,
        "account_reuse_level": "Medium",
    },

    "CS_006": {
        "rotation_level": "High",
        "org_spread": 2,
        "account_reuse_level": "High",
    },

    "CS_007": {
        "rotation_level": "Low",
        "org_spread": 3,
        "account_reuse_level": "Medium",
    },

    "CS_008": {
        "rotation_level": "Medium",
        "org_spread": 3,
        "account_reuse_level": "High",
    },

    "CS_009": {
        "rotation_level": "High",
        "org_spread": 3,
        "account_reuse_level": "Low",
    },

    "CS_010": {
        "rotation_level": "Low",
        "org_spread": 5,
        "account_reuse_level": "High",
    },

    "CS_011": {
        "rotation_level": "Medium",
        "org_spread": 5,
        "account_reuse_level": "Low",
    },

    "CS_012": {
        "rotation_level": "High",
        "org_spread": 5,
        "account_reuse_level": "Medium",
    },
}


# =========================================================
# CREATE CONFIGURATION FOR ONE CAMPAIGN REALIZATION
# =========================================================

def build_campaign_config(
    scenario_id: str,
    seed: int
):

    if scenario_id not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario: {scenario_id}"
        )

    scenario = SCENARIOS[scenario_id]

    rotation_level = scenario["rotation_level"]
    org_spread = scenario["org_spread"]
    account_reuse_level = (
        scenario["account_reuse_level"]
    )

    rip_target = ROTATION_LEVELS[
        rotation_level
    ]

    if account_reuse_level is None:
        raccount_target = None
    else:
        raccount_target = (
            ACCOUNT_REUSE_LEVELS[
                account_reuse_level
            ]
        )

    # Deterministic organization selection
    rng = random.Random(seed)

    if org_spread == 5:
        targeted_organizations = ORGANIZATIONS.copy()
    else:
        targeted_organizations = rng.sample(
            ORGANIZATIONS,
            org_spread
        )

    campaign_id = (
        f"{scenario_id}_SEED{seed}"
    )

    config = {
        "scenario_id": scenario_id,
        "campaign_id": campaign_id,
        "seed": seed,

        "rotation_level": rotation_level,
        "RIP_target": rip_target,

        "Sorg": org_spread,

        "account_reuse_level":
            account_reuse_level,

        "Raccount_target":
            raccount_target,

        "campaign_duration_minutes":
            CAMPAIGN_DURATION_MINUTES,

        "num_credential_identities":
            NUM_CREDENTIAL_IDENTITIES,

        "min_attempts_per_account":
            MIN_ATTEMPTS_PER_ACCOUNT,

        "max_attempts_per_account":
            MAX_ATTEMPTS_PER_ACCOUNT,

        "success_probability":
            SUCCESS_PROBABILITY,

        "targeted_organizations":
            targeted_organizations,
    }

    return config

# =========================================================
# CALCULATE NUMBER OF LOCAL TARGET USERS
# =========================================================


def calculate_local_target_counts(config):

    targeted_orgs = config["targeted_organizations"]

    total_credentials = (
        config["num_credential_identities"]
    )

    raccount_target = (
        config["Raccount_target"]
    )

    # Single-organization control scenario
    if config["Sorg"] == 1:

        return {
            targeted_orgs[0]: total_credentials
        }

    # Number of credentials reused across organizations
    reused_credentials = round(
        total_credentials * raccount_target
    )

    # Credentials appearing in only one organization
    nonreused_credentials = (
        total_credentials - reused_credentials
    )

    # Divide non-reused credentials as evenly as possible
    base_count = (
        nonreused_credentials
        // len(targeted_orgs)
    )

    remainder = (
        nonreused_credentials
        % len(targeted_orgs)
    )

    local_target_counts = {}

    for index, org in enumerate(targeted_orgs):

        extra = 1 if index < remainder else 0

        local_target_counts[org] = (
            reused_credentials
            + base_count
            + extra
        )

    return local_target_counts


# =========================================================
# SELECT LOCAL USERS DETERMINISTICALLY
# =========================================================

def select_local_users(
    organization: str,
    number_of_users: int,
    seed: int
):

    parquet_path = (
        ORGANIZATIONS_DIR
        / f"organization={organization}"
        / "data_0.parquet"
    )

    if not parquet_path.exists():

        raise FileNotFoundError(
            f"Organization dataset not found: "
            f"{parquet_path}"
        )

    query = f"""
        SELECT DISTINCT "User ID"
        FROM read_parquet('{parquet_path.as_posix()}')
        WHERE "User ID" IS NOT NULL
        ORDER BY hash(
            CAST("User ID" AS VARCHAR)
            || ':{seed}:{organization}'
        )
        LIMIT {number_of_users}
    """

    selected_users = (
        duckdb.sql(query)
        .fetchall()
    )

    selected_users = [
        row[0]
        for row in selected_users
    ]

    if len(selected_users) != number_of_users:

        raise ValueError(
            f"{organization}: requested "
            f"{number_of_users} users but only "
            f"{len(selected_users)} were selected."
        )

    return selected_users


# =========================================================
# SELECT TARGET USERS FOR ALL PARTICIPATING ORGANIZATIONS
# =========================================================

def select_campaign_target_users(config):

    local_target_counts = (
        calculate_local_target_counts(config)
    )

    selected_targets = {}

    for organization, count in (
        local_target_counts.items()
    ):

        selected_targets[organization] = (
            select_local_users(
                organization=organization,
                number_of_users=count,
                seed=config["seed"]
            )
        )

    return selected_targets

# =========================================================
# MAP SYNTHETIC CREDENTIAL IDENTITIES TO LOCAL USERS
# =========================================================


def build_credential_mapping(
    config,
    selected_targets
):

    total_credentials = (
        config["num_credential_identities"]
    )

    targeted_orgs = (
        config["targeted_organizations"]
    )

    # Single-organization campaigns have no
    # cross-organizational credential reuse.
    if config["Sorg"] == 1:

        reused_credentials = 0

    else:

        reused_credentials = round(
            total_credentials
            * config["Raccount_target"]
        )

    campaign_id = config["campaign_id"]

    credential_mapping = {
        org: []
        for org in targeted_orgs
    }

    # -----------------------------------------------------
    # Reused credentials
    # -----------------------------------------------------

    reused_credential_ids = [
        f"{campaign_id}_CRED_{i:03d}"
        for i in range(
            1,
            reused_credentials + 1
        )
    ]

    # Same hidden credential identity appears
    # in every targeted organization, but maps
    # to a different local User ID.
    for org in targeted_orgs:

        local_users = selected_targets[org]

        for index, credential_id in enumerate(
            reused_credential_ids
        ):

            credential_mapping[org].append(
                {
                    "synthetic_credential_id":
                        credential_id,

                    "User ID":
                        local_users[index],

                    "is_reused_credential":
                        True,
                }
            )

    # -----------------------------------------------------
    # Organization-specific credentials
    # -----------------------------------------------------

    next_credential_number = (
        reused_credentials + 1
    )

    for org in targeted_orgs:

        local_users = selected_targets[org]

        # Users after the reused-credential users
        unique_local_users = (
            local_users[reused_credentials:]
        )

        for user_id in unique_local_users:

            credential_id = (
                f"{campaign_id}_CRED_"
                f"{next_credential_number:03d}"
            )

            credential_mapping[org].append(
                {
                    "synthetic_credential_id":
                        credential_id,

                    "User ID":
                        user_id,

                    "is_reused_credential":
                        False,
                }
            )

            next_credential_number += 1

    # -----------------------------------------------------
    # Integrity check
    # -----------------------------------------------------

    generated_unique_credentials = (
        next_credential_number - 1
    )

    if (
        generated_unique_credentials
        != total_credentials
    ):

        raise ValueError(
            "Credential mapping integrity error: "
            f"expected {total_credentials} "
            "credential identities but generated "
            f"{generated_unique_credentials}."
        )

    return credential_mapping

# =========================================================
# VERIFY CREDENTIAL MAPPING
# =========================================================


def verify_credential_mapping(
    config,
    credential_mapping
):

    credential_to_orgs = {}

    for org, mappings in (
        credential_mapping.items()
    ):

        for mapping in mappings:

            credential_id = (
                mapping[
                    "synthetic_credential_id"
                ]
            )

            if credential_id not in (
                credential_to_orgs
            ):

                credential_to_orgs[
                    credential_id
                ] = set()

            credential_to_orgs[
                credential_id
            ].add(org)

    total_unique_credentials = len(
        credential_to_orgs
    )

    reused_credentials = sum(
        1
        for orgs in credential_to_orgs.values()
        if len(orgs) > 1
    )

    if config["Sorg"] == 1:

        raccount_actual = None

    else:

        raccount_actual = (
            reused_credentials
            / total_unique_credentials
        )

    print()
    print("=" * 60)
    print("CREDENTIAL MAPPING VERIFICATION")
    print("=" * 60)

    print(
        "Total unique credential identities:",
        total_unique_credentials
    )

    print(
        "Credentials reused across organizations:",
        reused_credentials
    )

    print(
        "Raccount actual:",
        raccount_actual
    )

    for org, mappings in (
        credential_mapping.items()
    ):

        print()
        print(
            f"{org}: "
            f"{len(mappings)} credential-to-user mappings"
        )

        print(
            "First 5 mappings:"
        )

        for mapping in mappings[:5]:

            print(
                " ",
                mapping[
                    "synthetic_credential_id"
                ],
                "-> User ID",
                mapping["User ID"],
                "| reused =",
                mapping[
                    "is_reused_credential"
                ]
            )

# =========================================================
# GENERATE SYNTHETIC ATTACKER IP ADDRESS
# =========================================================


def create_synthetic_ip(index):

    # 198.18.0.0/15 is reserved for testing/benchmarking.
    # We use these addresses only inside the offline simulation.

    third_octet = index // 254
    fourth_octet = (index % 254) + 1

    if third_octet > 255:
        raise ValueError(
            "Too many synthetic attacker IPs requested."
        )

    return (
        f"198.18.{third_octet}.{fourth_octet}"
    )


# =========================================================
# GENERATE SYNTHETIC AUTHENTICATION EVENTS
# =========================================================

def generate_synthetic_events(
    config,
    credential_mapping
):

    if "campaign_start" not in config:
        raise ValueError(
            "campaign_start is not defined. "
            "Use --pilot for the current test."
        )

    rng = random.Random(
        config["seed"] + 500000
    )

    campaign_start = datetime.fromisoformat(
        config["campaign_start"]
    )

    campaign_end = (
        campaign_start
        + timedelta(
            minutes=config[
                "campaign_duration_minutes"
            ]
        )
    )

    events = []

    # -----------------------------------------------------
    # Create event shells
    # -----------------------------------------------------

    for organization, mappings in (
        credential_mapping.items()
    ):

        for mapping in mappings:

            number_of_attempts = rng.randint(
                config[
                    "min_attempts_per_account"
                ],
                config[
                    "max_attempts_per_account"
                ]
            )

            for _ in range(number_of_attempts):

                offset_seconds = rng.uniform(
                    0,
                    config[
                        "campaign_duration_minutes"
                    ] * 60
                )

                timestamp = (
                    campaign_start
                    + timedelta(
                        seconds=offset_seconds
                    )
                )

                login_successful = (
                    rng.random()
                    < config[
                        "success_probability"
                    ]
                )

                events.append(
                    {
                        "organization":
                            organization,

                        "User ID":
                            mapping["User ID"],

                        "Login Timestamp":
                            timestamp,

                        "LoginSuccessful":
                            login_successful,

                        "synthetic_credential_id":
                            mapping[
                                "synthetic_credential_id"
                            ],

                        "is_reused_credential":
                            mapping[
                                "is_reused_credential"
                            ],

                        "is_synthetic":
                            True,

                        "credential_stuffing_label":
                            1,

                        "scenario_id":
                            config["scenario_id"],

                        "campaign_id":
                            config["campaign_id"],
                    }
                )

    # -----------------------------------------------------
    # Determine number of attacker IPs
    # -----------------------------------------------------

    total_attempts = len(events)

    number_of_unique_ips = round(
        total_attempts
        * config["RIP_target"]
    )

    number_of_unique_ips = max(
        1,
        min(
            number_of_unique_ips,
            total_attempts
        )
    )

    attacker_ips = [
        create_synthetic_ip(i)
        for i in range(
            number_of_unique_ips
        )
    ]

    # Guarantee every generated attacker IP
    # appears at least once.
    ip_assignments = attacker_ips.copy()

    while len(ip_assignments) < total_attempts:

        ip_assignments.append(
            rng.choice(attacker_ips)
        )

    rng.shuffle(ip_assignments)

    # -----------------------------------------------------
    # Attach IPs and unique event IDs
    # -----------------------------------------------------

    for index, event in enumerate(events):

        event["IP Address"] = (
            ip_assignments[index]
        )

        event["campaign_event_id"] = (
            f'{config["campaign_id"]}'
            f'_EVT_{index + 1:05d}'
        )

    # Keep output ordered by timestamp
    events.sort(
        key=lambda event:
            event["Login Timestamp"]
    )

    return events, campaign_start, campaign_end


# =========================================================
# VERIFY SYNTHETIC EVENTS
# =========================================================

def verify_synthetic_events(
    config,
    events,
    campaign_start,
    campaign_end
):

    total_attempts = len(events)

    unique_ips = {
        event["IP Address"]
        for event in events
    }

    successful_attempts = sum(
        1
        for event in events
        if event["LoginSuccessful"]
    )

    failed_attempts = (
        total_attempts
        - successful_attempts
    )

    rip_actual = (
        len(unique_ips)
        / total_attempts
    )

    icampaign = (
        total_attempts
        / config[
            "campaign_duration_minutes"
        ]
    )

    print()
    print("=" * 60)
    print("SYNTHETIC EVENT VERIFICATION")
    print("=" * 60)

    print(
        "Campaign start:",
        campaign_start
    )

    print(
        "Campaign end:",
        campaign_end
    )

    print(
        "Total synthetic attempts:",
        total_attempts
    )

    print(
        "Unique attacker IPs:",
        len(unique_ips)
    )

    print(
        "RIP target:",
        config["RIP_target"]
    )

    print(
        "RIP actual:",
        round(rip_actual, 4)
    )

    print(
        "Successful attempts:",
        successful_attempts
    )

    print(
        "Failed attempts:",
        failed_attempts
    )

    print(
        "Campaign intensity:",
        round(icampaign, 4),
        "attempts per minute"
    )

    print()

    for organization in (
        config["targeted_organizations"]
    ):

        org_events = [
            event
            for event in events
            if event["organization"]
            == organization
        ]

        print(
            f"{organization}: "
            f"{len(org_events)} synthetic events"
        )

    print()
    print("First 5 generated events:")

    for event in events[:5]:

        print(
            event[
                "campaign_event_id"
            ],
            "|",
            event["organization"],
            "| User:",
            event["User ID"],
            "| IP:",
            event["IP Address"],
            "| Time:",
            event["Login Timestamp"],
            "| Success:",
            event["LoginSuccessful"]
        )

# =========================================================
# SAVE SYNTHETIC EVENTS
# =========================================================


def save_synthetic_events(
    config,
    events
):

    output_dir = (
        SYNTHETIC_EVENTS_DIR
        / config["campaign_id"]
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    for organization in (
        config["targeted_organizations"]
    ):

        org_events = [
            event
            for event in events
            if event["organization"]
            == organization
        ]

        df = pd.DataFrame(
            org_events
        )

        output_path = (
            output_dir
            / f"{organization}.parquet"
        )

        duckdb.register(
            "synthetic_df",
            df
        )

        duckdb.sql(
            f"""
            COPY synthetic_df
            TO '{output_path.as_posix()}'
            (FORMAT PARQUET)
            """
        )

        duckdb.unregister(
            "synthetic_df"
        )

        print(
            f"Saved {len(df)} events -> "
            f"{output_path}"
        )

    return output_dir

# =========================================================
# DISPLAY CONFIGURATION
# =========================================================


def print_campaign_config(config):

    print("=" * 60)
    print("CREDENTIAL-STUFFING CAMPAIGN CONFIGURATION")
    print("=" * 60)

    print(
        "Scenario:",
        config["scenario_id"]
    )

    print(
        "Campaign:",
        config["campaign_id"]
    )

    print(
        "Seed:",
        config["seed"]
    )

    print(
        "IP rotation level:",
        config["rotation_level"]
    )

    print(
        "RIP target:",
        config["RIP_target"]
    )

    print(
        "Organization spread:",
        config["Sorg"]
    )

    print(
        "Targeted organizations:",
        ", ".join(
            config["targeted_organizations"]
        )
    )

    print(
        "Account reuse level:",
        config["account_reuse_level"]
    )

    print(
        "Raccount target:",
        config["Raccount_target"]
    )

    print(
        "Campaign duration:",
        config["campaign_duration_minutes"],
        "minutes"
    )

    print(
        "Credential identities:",
        config["num_credential_identities"]
    )

    print(
        "Attempts per account:",
        f'{config["min_attempts_per_account"]}-'
        f'{config["max_attempts_per_account"]}'
    )

    print(
        "Success probability:",
        config["success_probability"]
    )


# =========================================================
# COMMAND-LINE ENTRY POINT
# =========================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description=(
            "Generate controlled offline "
            "credential-stuffing campaigns."
        )
    )

    parser.add_argument(
        "--scenario",
        required=True,
        choices=sorted(SCENARIOS.keys()),
        help="Campaign scenario ID."
    )

    parser.add_argument(
        "--seed",
        required=True,
        type=int,
        help="Fixed random seed."
    )

    parser.add_argument(
        "--pilot",
        action="store_true",
        help="Run a small pilot campaign."
    )

    args = parser.parse_args()

    campaign_config = build_campaign_config(
        args.scenario,
        args.seed
    )

    if args.pilot:
        campaign_config["num_credential_identities"] = (
            PILOT_NUM_CREDENTIAL_IDENTITIES
        )

        campaign_config["campaign_start"] = (
            PILOT_CAMPAIGN_START
        )

        campaign_config["campaign_id"] = (
            campaign_config["campaign_id"]
            + "_PILOT"
        )

    print_campaign_config(
        campaign_config
    )

    target_users = (
        select_campaign_target_users(
            campaign_config
        )
    )

    print()
    print("=" * 60)
    print("LOCAL TARGET USER SELECTION")
    print("=" * 60)

    for organization, users in target_users.items():

        print(
            f"{organization}: "
            f"{len(users)} local target users"
        )

        print(
            "First 5 selected User IDs:",
            users[:5]
        )

    credential_mapping = (
        build_credential_mapping(
            campaign_config,
            target_users
        )
    )

    verify_credential_mapping(
        campaign_config,
        credential_mapping
    )

    synthetic_events, campaign_start, campaign_end = (
        generate_synthetic_events(
            campaign_config,
            credential_mapping
        )
    )

    verify_synthetic_events(
        campaign_config,
        synthetic_events,
        campaign_start,
        campaign_end
    )

    output_dir = save_synthetic_events(
        campaign_config,
        synthetic_events
    )

    print()
    print(
        "Campaign saved to:",
        output_dir
    )
