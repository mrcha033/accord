# in-toto 스타일 메타데이터 헤더

사용 방식: 문서/코드/요약 파일 최상단에 HTML 주석 형태로 삽입하여 파서와 사람 모두 읽을 수 있도록 유지. DSSE 서명 파일(`.dsse`)과 연계해 해시 검증을 수행.

---

## 헤더 구조
- **_type**: in-toto Statement 버전(URL). 예) `https://in-toto.io/Statement/v0.1`
- **subject**: 대상 산출물 배열. 각 요소는 `name`(경로/ID)과 `digest`(sha256 등)를 포함.
- **predicateType**: 사용한 프로세스 유형 URI. 정책/요약/코드 등 카테고리별로 관리.
- **predicate**: 실제 메타데이터. 도구, 실행환경, GEDI 의사결정 링크, 검증 상태, `materials` 등을 포함.
- **signers**: 참여자 및 서명 방식 명시. 최종 서명은 DSSE 파일에서 수행.

> **변경점 요약**
> - 기존 `statement_type` → `_type`, `predicate_type` → `predicateType`, `subject[].uri` → `subject[].name`
> - `materials`는 Statement 최상단이 아닌 `predicate.materials`로 이동
> - DSSE `payloadType`은 `application/vnd.in-toto+json`으로 고정하여 서명/검증 툴과 호환

---

## Markdown 헤더 템플릿

```markdown
<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "<상대 경로 또는 문서 ID>"
      digest:
        sha256: "<산출물 해시>"
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-<ID>"
      agent_role: "<역할 명칭>"
      coach_id: "AGENT-<ID | NONE>"
    process:
      toolchain:
        - name: "<툴/스크립트>"
          version: "<버전>"
      mcp_sessions:
        - server: "<mcp endpoint>"
          session_id: "<UUID>"
    governance:
      gedi_ballot_uri: "<투표 로그 경로 | NONE>"
      decision_rule: "<예: condorcet>"
    quality_checks:
      review_status: "<pending|approved>"
      tests:
        - name: "<테스트명>"
          result: "<pass|fail|n/a>"
    security:
      isolation_level: "<sandbox|trusted>"
      provenance_level: "slsa-lvl1"
    materials:
      - name: "<입력 문서/데이터>"
        digest:
          sha256: "<입력 해시>"
        role: "input"
  signers:
    - id: "AGENT-<ID>"
      signature_ref: "attestations/<파일명>.dsse"
-->
```

---

## 예시 (Policy Update 문서 헤더)

```markdown
<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "org/policy/2024-07-05-gedi-rollout.md"
      digest:
        sha256: "f1bfc4f86f8d4e5cf3a9e14d047c9e5f0f1733b59dcb5eeeaf37b193f3b6abfe"
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-PO01"
      agent_role: "Policy Orchestrator"
      coach_id: "AGENT-COACH01"
    process:
      toolchain:
        - name: "policy-synth"
          version: "0.3.2"
      mcp_sessions:
        - server: "mcp://file-system@v1"
          session_id: "98d1a876-1f40-4a54-8ac3-d75e80c6d3be"
    governance:
      gedi_ballot_uri: "logs/gedi/2024-07-04-rollout.json"
      decision_rule: "condorcet"
    quality_checks:
      review_status: "approved"
      tests:
        - name: "policy-lint"
          result: "pass"
    security:
      isolation_level: "sandbox"
      provenance_level: "slsa-lvl1"
    materials:
      - name: "org/_registry/AGENT-PO01.alou.md"
        digest:
          sha256: "d4e0851dc58af53bba1ce1ea2c5afbbf8923a8d2d2fa31b88d93707aa0e1f9f7"
        role: "reference"
      - name: "bus/gedi/2024-07-04-vote.log"
        digest:
          sha256: "b31bd6a039b11b3688e02f651e2b44531b314ae52f78c87a9b1d4c6172bbf44c"
        role: "ballot_log"
  signers:
    - id: "AGENT-PO01"
      signature_ref: "attestations/2024-07-05-gedi-rollout.dsse"
    - id: "AGENT-COACH01"
      signature_ref: "attestations/2024-07-05-gedi-rollout.dsse"
-->
```

---

## DSSE 규약 요약
- **payloadType**: 항상 `application/vnd.in-toto+json`
- **payload**: 위 Statement를 JSON 직렬화한 뒤 Base64 인코딩
- **서명 알고리즘**: Ed25519 등. PAE(Pre-Authentication Encoding) 규칙에 따라 `payloadType`과 `payload`를 결합해 서명/검증

```
length(type) = len(payloadType)
length(payload) = len(payload)
PAE = "DSSEv1 {length(type)} {payloadType} {length(payload)} {payload}"
```

`provtools.py` 스크립트를 사용하면 Statement 검증, 해시 점검, DSSE 서명을 일괄 처리할 수 있다.
