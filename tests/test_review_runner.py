from auto_skills.review_runner import ReviewDecision, parse_review_decision


def test_parse_review_decision_accepts_json_code_fence():
    text = '''```json
    {
      "action": "create",
      "skill_name": "daily-report",
      "reason": "Reusable workflow",
      "skill_markdown": "---\\nname: daily-report\\ndescription: Write reports.\\n---\\n\\n# Daily Report\\nBody",
      "patch_notes": "initial"
    }
    ```'''

    decision = parse_review_decision(text)

    assert decision.action == "create"
    assert decision.skill_name == "daily-report"
    assert decision.reason == "Reusable workflow"


def test_parse_review_decision_turns_bad_json_into_noop():
    decision = parse_review_decision("not json")

    assert decision == ReviewDecision(action="noop", reason="Invalid review JSON")


def test_parse_review_decision_rejects_unknown_action():
    decision = parse_review_decision('{"action":"delete","skill_name":"x"}')

    assert decision.action == "delete"
    assert decision.skill_name == "x"
