from pathlib import Path
import argparse
import random


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