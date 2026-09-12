import hashlib
import json
from bganalyzer.recommendations.policy import get_policy, policy_fingerprint, validated_policy_audit


def test_policy_audit_requires_matching_policy_and_evidence(tmp_path):
    policy = get_policy("policy-v1")
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"synthetic":true}')
    audit = {"status": "APPROVED", "decision": "approved", "policy_version": policy.version,
             "policy_hash": policy_fingerprint(policy), "evidence_ids": [evidence.name],
             "evidence_hashes": {evidence.name: hashlib.sha256(evidence.read_bytes()).hexdigest()}}
    path = tmp_path / "policy_review.json"
    path.write_text(json.dumps(audit))
    assert validated_policy_audit(policy, path)
    evidence.write_text('{"changed":true}')
    assert not validated_policy_audit(policy, path)
    audit["evidence_hashes"][evidence.name] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    audit["policy_hash"] = "unrelated"
    path.write_text(json.dumps(audit))
    assert not validated_policy_audit(policy, path)


def test_claimed_approval_alone_is_insufficient(tmp_path):
    path = tmp_path / "policy_review.json"
    path.write_text(json.dumps({"status": "APPROVED", "decision": "approved", "policy_hash": "x", "evidence_ids": ["test"]}))
    assert not validated_policy_audit(get_policy("policy-v1"), path)
