"""Subphase 1 policy guards, independent of any trainer or sampler."""
from datetime import datetime, timedelta


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounds(protocol, split):
    require(split in protocol['splits_half_open'], 'Unknown split')
    return tuple(datetime.fromisoformat(t) for t in protocol['splits_half_open'][split])


def validate_branch(protocol, split, anchor, end, history_start, history_end):
    lo, hi = bounds(protocol, split)
    require(lo <= anchor < end <= hi, 'Replay outside chronological split')
    require(end == anchor + timedelta(hours=1), 'Expected accepted one-hour replay')
    require(history_start == anchor - timedelta(days=7) and history_end == anchor,
            'Warm-up must be seven days strictly before anchor')
    require(history_start >= bounds(protocol, 'TRAIN')[0], 'Warm-up before available source coverage')


def scoring_times(protocol, anchor):
    return tuple(anchor + timedelta(minutes=n) for n in protocol['scoring']['grid_offsets_minutes'])


def require_use(protocol, split, purpose):
    """Future pipeline entry points must call this guard; not a complete access sandbox."""
    bounds(protocol, split)
    allowed = {
        'fit': {'TRAIN'}, 'preprocessing_fit': {'TRAIN'},
        'feature_selection': {'TRAIN', 'VAL'}, 'hyperparameter_selection': {'VAL'},
        'early_stopping': {'VAL'}, 'model_selection': {'VAL'},
        'comparator_selection': {'VAL'}, 'threshold_calibration': {'VAL'},
        'integrity_audit': {'TRAIN', 'VAL', 'TEST'},
        'descriptive_audit': {'TRAIN', 'VAL', 'TEST'},
    }
    require(purpose in allowed and split in allowed[purpose], 'Split forbidden for requested purpose')


def validate_target(protocol, row, organization, split, asof):
    lo, hi = bounds(protocol, split)
    require(row['organization'] == organization, 'Cross-organization label')
    require(row['split'] == split and row['label_time'] == asof and lo <= asof < hi,
            'Label split/time mismatch')
    y = row['node_label']
    require(y in (-1, 0, 1) and type(row['supervision_eligible']) is bool,
            'Invalid supervision domain')
    require(row['supervision_eligible'] == (y != -1), 'Mask mismatch')
    if y == 1:
        evidence = row['latest_positive_evidence']
        require(isinstance(evidence, datetime) and asof - timedelta(minutes=10) < evidence <= asof,
                'Future or expired positive evidence')
        require(row['positive_expires_at'] == evidence + timedelta(minutes=10), 'Incorrect expiry')
    else:
        require(row['latest_positive_evidence'] is None and row['positive_expires_at'] is None,
                'Nonpositive state carries positive evidence')


def require_checkpoint(organization, checkpoint_org, clock, requested_time, branch, checkpoint_branch):
    require(organization == checkpoint_org, 'Cross-organization checkpoint')
    require(branch == checkpoint_branch, 'Cross-branch checkpoint')
    require(clock <= requested_time, 'Future checkpoint cannot initialize earlier state')
