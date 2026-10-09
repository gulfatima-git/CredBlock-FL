from pathlib import Path
import argparse
import random
import duckdb


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

    args = parser.parse_args()

    campaign_config = build_campaign_config(
        args.scenario,
        args.seed
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