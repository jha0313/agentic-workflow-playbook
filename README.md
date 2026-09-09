# 워크플로우와 검증 — 에이전틱 워크플로우 플레이북

<div align="center">

**Jae Ha** — Meta 시니어 엔지니어 · 9년 차 · Dev Productivity champion  
<sub>메타에서 실제로 해보고 배운 것을 계속 공유합니다</sub>

[![YouTube @sv.developer](https://img.shields.io/badge/YouTube-%40sv.developer-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/@sv.developer)
[![Course](https://img.shields.io/badge/Course-Claude%20Code%20%26%20Agentic%20Workflow-1F6FEB?style=for-the-badge&logo=bookstack&logoColor=white)](https://fastcampus.co.kr/data_online_svvibecoding)
[![LinkedIn](<https://img.shields.io/badge/LinkedIn-jae--sang--ha-0A66C2?style=for-the-badge&logo=data:image/svg%2Bxml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHZpZXdCb3g9JzAgMCAyNCAyNCc+PHRleHQgeD0nMS41JyB5PScxOS41JyBmb250LWZhbWlseT0nQXJpYWwsSGVsdmV0aWNhLHNhbnMtc2VyaWYnIGZvbnQtd2VpZ2h0PSdib2xkJyBmb250LXNpemU9JzE5JyBmaWxsPSd3aGl0ZSc+aW48L3RleHQ+PC9zdmc+>)](https://www.linkedin.com/in/jae-sang-ha/)
[![KakaoTalk Open Chat](https://img.shields.io/badge/Open%20Chat-KakaoTalk-FEE500?style=for-the-badge&logo=kakaotalk&logoColor=000000)](https://open.kakao.com/o/g3Os2Lri)

<table>
<tr><td align="right">▶️ <b>유튜브</b></td><td><a href="https://www.youtube.com/@sv.developer">@sv.developer</a> — Claude Code · Agentic Engineering</td></tr>
<tr><td align="right">🎓 <b>강의</b></td><td><a href="https://fastcampus.co.kr/data_online_svvibecoding">실리콘밸리 엔지니어의 Claude Code — 바이브 코딩 &amp; 에이전틱 워크플로우 실전 로드맵</a> (일부 강의 무료 공개)</td></tr>
<tr><td align="right">💼 <b>링크드인</b></td><td><a href="https://www.linkedin.com/in/jae-sang-ha/">jae-sang-ha</a></td></tr>
<tr><td align="right">💬 <b>오픈카톡방</b></td><td><a href="https://open.kakao.com/o/g3Os2Lri">open.kakao.com/o/g3Os2Lri</a> — 세미나 질문</td></tr>
</table>

</div>

삼성전자 DX 세미나 2차(2026년 9월) 자료. AI에게 칸 하나가 아니라 **절차 전체**를 넘기는 6단계 루프(`0 맥락 → 1 의도 → 2 스펙 → 3 분해 → 4 구현 → 5 검증 → 6 개선`)와, 그 결과를 믿게 만드는 검증 구조(5-a 게이트 / 5-b 외부검증)를 다룬다.

## 여기 있는 것

| 경로 | 내용 |
|---|---|
| `playbook/워크플로우-플레이북.md` | 배포용 플레이북. **에이전트에게 그대로 읽히는 용도**로 썼다 |
| `playbook/워크플로우-플레이북.html` | 같은 내용의 인터랙티브 페이지. 세미나 블록 1·4에서 화면에 띄운 그 페이지 |
| `playbook/드롭인-조율자-템플릿.md` | 새 작업을 시작할 때 첫 프롬프트로 붙여 넣는 조율자 템플릿 |
| `playbook/데모-프롬프트.md` | 두 데모에서 실제로 보낸 여덟 줄 프롬프트 |
| `slides/index.html` | 슬라이드 8장 (표지 · 자기소개 · 설문 · 마무리 4장 · 마지막 멘트) — 단일 파일, ←/→ 로 이동 |
| `logs/pm-log.html` | 비개발 데모 — 기획자 페르소나가 빈 폴더에서 로드맵 진척 대시보드를 만든 전체 에이전트 로그 (루프 2회) |
| `logs/dev-log.html` | 개발 데모 — 기존 서비스에 제품 분석 계측을 넣은 전체 에이전트 로그 (조율자 + 팀메이트 18세션) |
| `tools/log2html.py` | Claude Code 세션 로그(JSONL) → 위 로그 뷰어 HTML 생성기 |

## 3분 안에 시작하기

1. 에이전트(Claude Code 등)에게 `playbook/워크플로우-플레이북.md`를 읽힌다.
2. `playbook/드롭인-조율자-템플릿.md`의 "이번 작업" 여섯 칸 중 **목표 한 줄만** 채워서 보낸다. 나머지 다섯 칸은 비워 둔다 — 1번 의도 단계에서 에이전트가 물어서 채우게 하는 것이 요점이다. 실제 예가 `playbook/데모-프롬프트.md`에 있다.
3. 첫 루프가 끝나면 `0-맥락.md`가 생긴다. 다음 루프는 그 파일만 읽고 시작하면 된다. 그게 자산이다.

플레이북에서 먼저 볼 곳 두 군데: **★ 5번은 두 층이다**(어디로 되돌아가는지가 다르다), **언제 쓰지 말아야 하나**.

## 로그 뷰어 직접 만들기

```bash
python3 tools/log2html.py \
  --title "내 작업" --subtitle "설명" --out my-log.html \
  ~/.claude/projects/<cwd를-인코딩한-폴더>/<세션>.jsonl [팀메이트-세션.jsonl ...]
```

첫 파일이 메인(조율자) 세션, 나머지는 팀메이트·서브에이전트 세션으로 시간순 병합된다. 에이전트가 답에 `[3] 분해`, `현재 위치: 5-a 통과` 처럼 단계를 적으면 단계 레일과 색이 자동으로 붙는다. 키·토큰·DSN·JWT 형태의 문자열은 `<REDACTED>`로 가린다.

## 주의

- `logs/`의 두 파일은 편집하지 않은 실제 작업 기록이다. 키·토큰·이메일·홈 경로는 가렸지만 프로젝트명과 파일명은 그대로 남아 있다.
- 플레이북은 특정 도구에 묶여 있지 않다. Claude Code 기준으로 썼지만 조율자·서브에이전트를 띄울 수 있는 환경이면 어디서든 같다.
