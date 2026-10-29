# herdr-llm-usage

[English](README.md) · **한국어**

[herdr](https://herdr.dev)에서 돌리는 에이전트의 LLM 쪽을 한곳에서 보는
플러그인입니다. 계정마다 구독 사용량이 얼마나 남았는지 보여주고, 실행 중인
세션을 끊지 않고 계정을 바꾸며, 에이전트 세션이 무엇으로 설정되어 있고 실제로
무엇을 쓰는지 보여줍니다.

- **사용량**: 저장한 모든 Claude Code·Codex 계정의 5시간·주간·모델별 사용량과
  리셋까지 남은 시간을 패널과 사이드바에 보여줍니다.
- **계정 전환**: Claude는 실행 중인 세션이 그대로 이어지면서 계정만 바뀝니다.
  Codex는 pane이 쉬는 상태가 되면 같은 세션을 새 로그인으로 다시 이어갑니다.
- **자동 전환**: Claude 계정이 기준치에 닿으면 남은 사용량이 가장 많은 계정,
  또는 주간 사용량이 가장 먼저 리셋되는 계정으로 자동으로 옮깁니다.
- **에이전트 모니터**: 작업 옆에 붙어서, 선택한 에이전트를 따라가며 실행 중인
  워크플로우, 지침 파일, 메모리, 스킬, MCP 서버, 훅, 설정을 보여주고 이 세션이
  실제로 쓴 것을 표시합니다. 마크다운 파일을 읽고, 프로젝트 메모리를 정리하고,
  스킬을 끄고 켤 수 있습니다.

![에이전트 모니터](assets/monitor.png)

<p>
  <img src="assets/panel-claude.png" alt="Claude 탭: 저장한 모든 계정의 사용량" width="49%">
  <img src="assets/panel-settings.png" alt="설정 탭" width="49%">
</p>

<sub>스크린샷의 계정과 세션은 예시입니다. 화면의 문구는 영어로 표시됩니다.</sub>

## 목차

- [이런 분께 맞습니다](#이런-분께-맞습니다)
- [빠른 시작](#빠른-시작)
- [설치](#설치)
- [패널: `prefix+u`](#패널-prefixu)
- [계정 추가와 전환](#계정-추가와-전환)
- [Claude 자동 전환](#claude-자동-전환)
- [에이전트 모니터: `prefix+m`](#에이전트-모니터-prefixm)
- [사이드바](#사이드바)
- [설정값](#설정값)
- [읽고 쓰는 파일](#읽고-쓰는-파일)
- [문제 해결](#문제-해결)
- [자주 묻는 질문](#자주-묻는-질문)
- [제거](#제거)
- [개인정보와 데이터](#개인정보와-데이터)

## 이런 분께 맞습니다

herdr에서 Claude Code나 Codex를 쓰고 있고, 아래 중 하나라도 해당한다면:

- 5시간 한도나 주간 한도에 걸리기 전에, 계정별로 미리 보고 싶다.
- 구독이 여러 개라서(회사·개인, 팀 좌석·Max 플랜 등) 로그아웃과 로그인을
  반복하며 바꿔 쓰고 있다.
- 프로젝트마다 에이전트가 다르게 행동하는데, 무엇을 불러오는지 보고 싶다.
  어떤 `CLAUDE.md` 파일들을 읽는지, 메모리가 얼마나 쌓였는지, 스킬 40개 중
  실제로 쓰는 게 무엇인지, 어떤 MCP 서버를 호출하는지.
- 워크플로우나 서브에이전트를 띄워 두고, 어떤 게 아직 돌고 있는지 알고 싶다.

각 기능은 따로따로 동작합니다. 사용량 보기는 추가 설치가 필요 없고, Claude
계정 전환에는 claude-swap이, 모니터에는 herdr의 에이전트 연동이 필요합니다.

## 빠른 시작

1. 플러그인을 설치하고 단축키 두 개를 추가한 뒤([설치](#설치) 참고), herdr에서
   **메뉴 → reload config**를 누릅니다.
2. `prefix+u`를 누릅니다. **Claude** 탭과 **Codex** 탭에 각 CLI에 로그인된
   계정과 사용량이 보입니다.
3. 여러 계정을 쓰려면: `s`로 현재 로그인을 저장하고, CLI에서 다음 계정으로
   로그인한 뒤(Claude Code에서는 `/login`, Codex는 `codex login`) 다시 `s`를
   누릅니다. 계정마다 반복합니다. 계정에서 `enter`를 누르면 그 계정으로
   바뀝니다.
4. 선택: **Settings** 탭에서 **Auto-switch**를 켜고 전략을 고릅니다. 한 턴이
   길어도 확인되도록 **Check while Claude works**도 켭니다.
5. 선택: **Settings** 탭에서 **Agent monitoring**을 켜고 `prefix+m`을
   누릅니다. herdr 사이드바에서 에이전트를 선택하면 모니터에 그 에이전트가
   나옵니다.

## 설치

```bash
herdr plugin install doldola/herdr-llm-usage
```

이후 업데이트는 `herdr plugin update`로 합니다. 그리고
`~/.config/herdr/config.toml`에 단축키를 추가합니다.

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "llm-usage.open"
description = "LLM usage"

[[keys.command]]
key = "prefix+m"
type = "plugin_action"
command = "llm-usage.monitor"
description = "Agent monitor"
```

단축키와 사이드바 줄은 herdr 클라이언트가 읽습니다. 바꾼 내용은 herdr에서
**메뉴 → reload config**로 적용하거나, detach 후 다시 attach하면 적용됩니다.
`herdr server reload-config`는 서버 설정만 다시 읽기 때문에 단축키에는 효과가
없습니다. 두 키 모두 herdr 기본값에서 비어 있는 키입니다. 이미 다른 기능에
쓰고 있다면 다른 키를 고르세요.

단축키 없이도 herdr 안의 셸에서 같은 동작을 실행할 수 있습니다.
`herdr plugin action invoke llm-usage.open`, `llm-usage.monitor`.

### 필요한 것

| 기능 | 필요한 것 |
|---|---|
| 전체 | herdr 0.7.5 이상, `python3`(3.8 이상, 표준 라이브러리만 사용), Linux 또는 macOS |
| Claude 계정 저장·전환, 자동 전환 | [claude-swap](https://github.com/realiti4/claude-swap): `uv tool install claude-swap`(또는 `pipx install claude-swap`). 없으면 Claude 탭에는 로그인된 계정 하나만 보입니다. |
| pane별 세션(Codex 재개, 에이전트 모니터) | 각 pane의 세션 ID를 알기 위한 herdr 연동: `herdr integration install claude`, `herdr integration install codex` |
| Codex 전환 | Codex가 로그인을 `auth.json`에 보관할 것(기본값 `cli_auth_credentials_store = "file"`) |

사용량은 구독 로그인(Claude Pro/Max/Team, Codex를 쓰는 ChatGPT 플랜)에서만
보입니다. API 키 로그인에는 5시간·주간 한도가 없으므로, 설정 탭의 다른 로그인
목록에만 표시됩니다.

## 패널: `prefix+u`

탭 네 개가 있는 팝업입니다. `←` `→`, `Tab` 또는 `1`–`4`로 탭을 바꾸고,
`↑` `↓`로 고르고, `r`로 새로고침, `q`로 닫습니다.

| 탭 | 보여주는 것 | 키 |
|---|---|---|
| **Claude** | 저장한 모든 계정의 5시간·주간·모델별 사용량 | `enter` 전환 · `b` 전략대로 전환 · `s` 현재 로그인 저장 · `x` 목록에서 제거 |
| **Codex** | 저장한 모든 계정과 그 플랜의 한도들 | `enter` 전환 · `b` 남은 사용량이 가장 많은 계정으로 · `s` 현재 로그인 저장 · `x` 목록에서 제거 |
| **Settings** | 자동 전환, 모니터링·훅 옵션, 백그라운드 동작 기록, 다른 로그인(Gemini, API 키) | `enter` 바꾸기 · `+` `-` 기준치 · `c` 자동 전환 확인을 지금 실행 |
| **Agents** | 모든 Claude·Codex pane: 실행 중인 도구, 컨텍스트, 도구 사용 횟수, 스킬, 읽은 마크다운 | `enter` 자세히 |

### 계정 화면 읽는 법

계정마다 사용량 한도별로 막대 하나, 사용한 비율, 리셋까지 남은 시간이
나옵니다.

```
› ● 1 work@example.com  [Example Inc]
        5h     ████████████░░░░░░  68.0%  ↻ 2h10m
        week   ███████░░░░░░░░░░░  41.0%  ↻ 3d4h
        fable  ████░░░░░░░░░░░░░░  22.0%  ↻ 3d4h
    2 me@example.com
        5h     ██░░░░░░░░░░░░░░░░  12.0%  ↻ 4h05m
        week   ████████████████░░  91.0%  ↻ 18h
```

- `●`는 지금 CLI에 로그인된 계정, `›`는 선택한 줄입니다. 숫자는 claude-swap의
  슬롯 번호이고, 팀 계정은 조직 이름이 함께 나옵니다.
- **5h**는 5시간 단위로 굴러가는 세션 한도, **week**는 주간 한도입니다. 일부
  플랜에는 모델별 주간 한도(예: Fable)가 따로 있어서 별도 줄로 나옵니다. Codex는
  플랜에 있는 한도만 보여주며, Pro 플랜에는 5시간 한도가 없습니다.
- 막대는 70%에서 노란색, 90%에서 빨간색이 됩니다. `↻`는 한도가 리셋되어
  비율이 다시 내려가기까지 남은 시간입니다.
- 사용량은 계정마다 최대 2분에 한 번 가져옵니다. `r`을 누르면 바로 가져옵니다.

## 계정 추가와 전환

### 계정 추가

각 CLI는 지금 로그인된 계정을 저장합니다. 현재 계정을 먼저 저장하고, 다음
계정으로 로그인한 뒤 그것도 저장합니다.

| | 로그인 | 저장 |
|---|---|---|
| Claude | Claude Code에서 `/login` | Claude 탭에서 `s` |
| Codex | `codex login` | Codex 탭에서 `s` |

로그인하면 그 CLI로 실행 중인 모든 세션이 쓰는 로그인이 바뀝니다. `x`는 저장한
계정을 목록에서 지울 뿐, 그 계정에서 로그아웃하지는 않습니다.

### 전환

- **Claude**: claude-swap이 Claude Code의 자격 증명 잠금을 잡은 상태에서 저장된
  로그인을 바꿔 끼웁니다. 실행 중인 세션은 재시작하지 않습니다. Linux에서는
  다음 요청부터, macOS에서는 약 30초 안에(키체인 캐시) 새 계정을 씁니다.
  대화, 컨텍스트, 실행 중인 도구는 그대로입니다.
- **Codex**: 실행 중인 Codex는 시작할 때의 로그인을 계속 쓰기 때문에, 전환하면
  1. 현재 `auth.json`을 그 계정 자리에 저장하고(가장 최신 토큰 유지), 고른
     로그인을 `auth.json`에 씁니다.
  2. 실행 중인 각 Codex pane이 쉬는 상태가 되기를 기다렸다가(최대 3시간)
     `/quit`을 보내고, 같은 pane에서 `codex <원래 옵션> resume <세션>`을
     실행합니다. 대화는 새 로그인으로 이어지며, 처음 실행할 때 넣었던 프롬프트는
     다시 보내지 않습니다.
  3. 다시 시작하지 못한 pane이 있으면 알림으로 알려줍니다.

  새로 여는 Codex pane은 바로 새 로그인을 씁니다. 저장된 Codex 로그인은
  `~/.codex/accounts/`(또는 `$CODEX_HOME/accounts/`)에 있으며, `auth.json`처럼
  본인만 읽을 수 있습니다.

`b`를 누르면 막대를 직접 비교하지 않아도, 설정한 전략대로(Claude) 또는 남은
사용량이 가장 많은 계정으로(Codex) 바꿉니다.

## Claude 자동 전환

설정 탭에서 켭니다. 에이전트 상태가 바뀔 때마다(최대 1분에 한 번) 현재 계정의
사용량을 기준치(기본 90%, `+` `-`로 조정)와 비교합니다.

| 전략 | 동작 |
|---|---|
| most quota left (남은 사용량 우선) | claude-swap 자체 자동 전환: 기준치에 닿으면 여유가 가장 많은 계정으로 옮깁니다. 재전환 대기와 오락가락 방지는 claude-swap의 방식을 따릅니다. |
| weekly reset soonest first (주간 리셋 임박 우선) | 쓸 수 있는 계정(모든 한도가 기준치 아래) 중 주간 한도가 가장 먼저 리셋되는 계정을 우선 씁니다. 곧 리셋될 사용량을 날리기 전에 먼저 쓰기 위해서입니다. 현재 계정이 기준치에 닿았거나, 쓸 수 있는 다른 계정이 6시간 넘게 먼저 리셋되면 옮기고, 옮긴 뒤 10분은 기다립니다. |

**주간 리셋 임박 우선**의 예시(기준치 90%):

| 계정 | 5h | week | 주간 리셋 |
|---|---|---|---|
| A (현재) | 40% | 55% | 5일 뒤 |
| B | 10% | 70% | 18시간 뒤 |
| C | 95% | 20% | 2일 뒤 |

B는 A보다 6시간 넘게 먼저 리셋되고 쓸 수 있는 상태이므로 B로 옮깁니다. 18시간
뒤면 사라질 B의 주간 사용량 30%를 먼저 쓰는 것입니다. C는 5시간 한도가 90%를
넘었으므로 건너뜁니다. B가 90%에 닿으면, 쓸 수 있는 계정 중 다음으로 먼저
리셋되는 계정이 이어받습니다.

**Also watch model**을 켜면 특정 모델의 주간 한도(예: Fable)도 함께 봅니다.
그 모델 한도가 찬 계정은 꽉 찬 계정으로 취급합니다. 전환할 때마다 새 계정과
이유를 herdr 알림으로 보여줍니다.

**Check while Claude works**를 켜면 Claude Code의 `settings.json`에 훅을
추가합니다. 도구 호출 뒤와 턴이 끝날 때 `herdr plugin action invoke
llm-usage.tick`을 백그라운드로 실행하며, 모든 pane을 합쳐 최대 1분에 한 번만
돌고, herdr 밖에서는 아무것도 하지 않습니다. herdr 자체 훅은 에이전트 상태가
바뀔 때만 돌기 때문에, 이게 없으면 한 턴이 길게 이어지는 동안에는 확인이
일어나지 않습니다. 다른 훅과 설정은 그대로 두고, 파일 옆에 백업을 한 번 저장하며,
끄면 이 훅만 지웁니다. 실행 중인 Claude 세션은 `/hooks`를 실행하거나 다시
시작하면 반영됩니다.

설정 탭의 **Background activity**에서는 사이드바 갱신, 자동 전환 확인, 모니터가
마지막으로 언제 돌았고 무엇을 했는지, 마지막 훅 오류가 무엇인지 볼 수 있습니다.
`c`를 누르면 자동 전환 확인을 바로 실행하고 그 판단을 보여줍니다.

## 에이전트 모니터: `prefix+m`

설정 탭에서 **Agent monitoring**을 켠 뒤(기본은 꺼짐) 모니터를 엽니다. 포커스된
pane의 오른쪽에 열리며, herdr 사이드바에서 에이전트를 선택하면 1초 안에 그
에이전트를 보여줍니다.

### 보여주는 것

| 섹션 | Claude | Codex |
|---|---|---|
| 머리말 | pane, 상태, 모델, 컨텍스트 사용량, 폴더, 세션 ID | 같음 |
| Workflows | 세션이 시작한 워크플로우·서브에이전트, 작업 목록 | — |
| Instructions | `CLAUDE.md` 체인, `.claude/rules` | `AGENTS.md` 체인 |
| Memory | 프로젝트 메모리 파일(`m`으로 정리) | — |
| Skills | 사용자·프로젝트·켜진 플러그인의 스킬, 사용 여부 표시(`s`로 관리) | `~/.codex/skills`, 프로젝트 스킬(`s`) |
| MCP servers | 사용자·로컬·프로젝트(`.mcp.json`) 서버, 사용한 서버 표시 | `config.toml`의 서버 |
| 그 밖에 | 서브에이전트, 명령, 플러그인, 훅, 권한 모드와 규칙 수 | 프롬프트, 모델, 추론 강도, 승인, 샌드박스 |
| This session | 실행 중인 도구, 도구 사용 횟수, 읽은 마크다운 파일 | 같음 |

이것들을 보여주는 이유: Instructions의 모든 파일, 메모리 인덱스, 모든 스킬의
설명, 모든 MCP 서버의 도구 목록은 첫 프롬프트 전에 모델의 컨텍스트에
들어갑니다. 긴 `CLAUDE.md` 체인, 오래된 항목이 쌓인 메모리 인덱스, 아무도 안
쓰는 스킬 60개는 매 턴 컨텍스트를 차지하고, 에이전트가 엉뚱한 도구를 고르는
일을 늘립니다. 모니터는 설정된 것과 세션이 실제로 쓴 것을 나란히 보여주어,
무엇을 줄이면 될지 알 수 있게 합니다. 파일마다 줄 수를 보여주는 것도 같은
이유입니다.

### Workflows

```
Workflows  1 running · 3 this session
  ◐ deploy-check          workflow · running 4m
  ✓ Find callers          Explore · 29s · 2m ago
  ✗ migrate-db            workflow · 1m · 10m ago
  tasks: 11 (8 done · 1 in progress)
    ▸ write tests
```

- 세션이 시작한 워크플로우와 서브에이전트(`Agent`/`Task` 도구)를 제목,
  서브에이전트 종류와 함께 보여줍니다.
- `◐`는 실행 중이며 지금까지 걸린 시간을, `✓` 완료와 `✗` 실패는 걸린 시간과
  끝난 시각을 보여줍니다. 실행 중인 것을 먼저, 그다음 최근에 끝난 것 다섯 개를
  보여줍니다.
- 일반 서브에이전트는 결과가 돌아오면 완료입니다. 백그라운드로 띄운
  워크플로우나 서브에이전트는 완료 알림이 대화에 들어오면 완료로 바뀝니다.
- `tasks:`는 세션의 작업 목록(`TaskCreate`/`TaskUpdate` 또는 `TodoWrite`)입니다.
  전체 개수, 완료한 개수, 진행 중인 항목을 보여줍니다.

### Skills

```
Skills  24 available · 3 used this session · 1 this turn
  ◉ loaded this turn  ● loaded earlier in the session  ○ not loaded
  ◉ code-review         plugin:engineering   Review code changes ...   ×2
  ● docx                user                 Create and edit Word ...  ×1
  ○ pdf                 user                 Read and fill PDFs ...
```

스킬은 다음 중 하나가 일어나면 "불러온" 것으로 봅니다.

1. 에이전트가 Skill 도구로 그 스킬을 불렀을 때
2. 사용자가 `/이름`으로 직접 실행했을 때
3. 에이전트가 그 스킬의 `SKILL.md`를 읽었을 때

`◉`는 마지막 프롬프트 이후에 불러온 스킬로, 지금 답변에 영향을 주고 있습니다.
`●`는 이 세션의 이전 턴에서 불러온 스킬, `○`는 불러오지 않은 스킬입니다. CLI는
모든 스킬의 설명을 모델에게 보여주지만, 스킬의 지침을 실제로 불러오는 것은 위
세 가지뿐입니다. 그래서 "쓸 수 있는" 스킬은 `○`로 남습니다. `×2`는 불러온
횟수입니다. 이번 턴에 불러온 스킬이 맨 위에 옵니다. 플러그인 스킬
(`plugin:skill`)과 폴더 이름으로 부른 스킬도 맞게 표시되며, 불러왔지만 디스크에
없는 스킬(내장 스킬)은 맨 아래에 따로 나옵니다.

### 조작

- `↑` `↓`로 줄을 고릅니다: 지침 파일, 규칙, 메모리 파일, 스킬의 `SKILL.md`,
  세션이 읽은 마크다운 파일. `enter`를 누르면 읽기 화면이 열립니다(`↑` `↓`,
  `space` / `b` 페이지 이동, `g` / `G` 처음과 끝, `esc` 돌아가기).
- 긴 섹션은 "… N more" 줄로 접혀 있습니다. 그 줄에서 `enter`를 누르면 펼쳐지고,
  `c`를 누르면 다시 모두 접힙니다.
- 줄은 pane 폭에 맞춰 줄바꿈되므로, 모니터가 좁아도 내용이 잘리지 않습니다.
- 선택한 에이전트가 다른 탭에 있으면 모니터가 그 탭의 오른쪽으로 따라갑니다.
  `f`로 끌 수 있습니다. 모니터 자체를 선택하면 마지막 에이전트가 화면에
  남습니다.
- `r`은 새로고침, `q`는 닫고 에이전트로 포커스를 돌려줍니다.

| 키 | 동작 |
|---|---|
| `↑` `↓` / `j` `k` | 줄 고르기 |
| `enter` | 파일 읽기, 섹션 펼치기, 메모리·스킬 관리 열기 |
| `c` | 긴 섹션 다시 접기 |
| `m` | 메모리 정리(Claude) |
| `s` | 스킬 관리 |
| `f` | 선택한 에이전트를 탭 너머로 따라가기 켜기/끄기 |
| `r` | 지금 새로고침 |
| `q` | 닫고 에이전트로 돌아가기 |

한글 두벌식 입력 상태에서도 단축키가 동작합니다. 한글 자모는 같은 자리의 영문
키로 읽습니다.

### 메모리 정리: `m`

Claude Code는 프로젝트 메모리를 `~/.claude/projects/<프로젝트>/memory/`에
마크다운 파일로 보관하고, `MEMORY.md`를 인덱스로 삼아 세션을 시작할 때마다
불러옵니다. 그 프로젝트 폴더의 모든 Claude 세션이 같은 메모리를 함께 쓰며,
세션이 무언가를 저장할수록 커집니다. `m`(또는 Memory 제목 줄에서 `enter`)을
누르면 선택한 에이전트의 프로젝트 메모리가 열립니다. `tab` / `shift+tab`
(또는 `→`)으로 필터를 바꿉니다.

| 필터 | 찾는 것 | 왜 문제인지 |
|---|---|---|
| all | 모든 메모리 파일 | |
| not in index | `MEMORY.md`가 링크하지 않는 파일 | Claude가 우연히만 찾게 됨 |
| duplicates | 제목이나 내용이 같은 파일 | 같은 사실을 두 번 불러오거나, 서로 다른 두 버전이 충돌 |
| old 30d+ | 30일 동안 바뀌지 않은 파일 | 더 이상 사실이 아닐 수 있음 |

`MEMORY.md`에 있지만 파일이 없어진 링크는 파일 목록 위에 따로 보여줍니다.

| 키 | 동작 |
|---|---|
| `enter` | 파일 읽기 |
| `d` | 보관: `memory/` 옆의 `memory-archive/<날짜>/`로 옮겨 Claude가 읽지 않게 하고, `MEMORY.md`의 해당 줄을 지웁니다 |
| `a` | 파일 설명을 이용해 `MEMORY.md`에 줄 추가 |
| `x` | 없어진 파일을 가리키는 `MEMORY.md` 줄 지우기 |
| `u` | 마지막 변경 되돌리기(여러 번 가능) |
| `esc` / `←` | 모니터로 돌아가기 |

아무것도 삭제하지 않습니다. 되돌리기는 그 변경이 건드린 줄과 파일만 되돌리므로,
그사이 다른 세션이 인덱스에 쓴 줄은 그대로 남습니다. 실행 중인 세션은 시작할 때
인덱스를 읽으므로, 변경은 새로 시작하는 세션부터 적용됩니다.

### 스킬 관리: `s`

`s`(또는 Skills 제목 줄에서 `enter`)를 누르면 선택한 에이전트가 쓸 수 있는 모든
스킬이 꺼 둔 것까지 포함해 나옵니다. Claude는 최근 30일 동안 그 프로젝트의 모든
세션에서 쓴 횟수를, Codex는 현재 세션에서 쓴 횟수를 셉니다. `tab` /
`shift+tab`(또는 `→`)으로 필터를 바꿉니다.

| 필터 | 찾는 것 | 왜 문제인지 |
|---|---|---|
| all | 모든 스킬 | |
| unused 30d | 어느 세션도 쓰지 않은 스킬 | 그래도 설명은 모든 세션의 컨텍스트를 차지함 |
| duplicates | 같은 이름의 스킬이 여러 곳에 있음 | CLI는 하나만 쓰므로, 나머지는 쓸모없거나 예상과 다르게 동작 |
| no description | 설명이 없는 스킬 | 에이전트가 언제 써야 할지 판단하지 못함 |
| disabled | 꺼 둔 스킬 | 다시 켤 때 |

| 키 | 동작 |
|---|---|
| `enter` | `SKILL.md` 읽기 |
| `d` | 끄기: 스킬 폴더를 skills 폴더 옆의 `skills-disabled/`로 옮깁니다. CLI는 그곳을 보지 않습니다 |
| `e` | 꺼 둔 스킬 다시 켜기 |
| `u` | 마지막 변경 되돌리기(여러 번 가능) |
| `esc` / `←` | 모니터로 돌아가기 |

플러그인 스킬은 그 플러그인이 관리하므로, Claude Code에서 `/plugin`으로
플러그인을 끄세요. 프로젝트 스킬을 끄면 프로젝트 안의 파일이 옮겨지므로 git에
변경으로 잡힙니다. 새 세션부터 반영되며, 실행 중인 세션은 시작할 때의 스킬
목록을 유지할 수 있습니다.

### 정보의 출처

설정 정보는 각 CLI가 세션 폴더에 대해 읽는 파일을 문서에 나온 위치에서 읽어 온
것입니다. 즉 무엇이 설정되어 있는지를 말할 뿐, CLI가 실제로 읽었다는 뜻은
아닙니다. 사용 정보(표시, 횟수, 워크플로우, 작업, 컨텍스트)는 세션의
트랜스크립트, 즉 각 CLI가 `~/.claude/projects/`나 `~/.codex/sessions/`에 남기는
기록에서 읽습니다. 트랜스크립트는 이어서 읽기 때문에, 새로고침할 때는 지난번
이후에 쓰인 부분만 읽습니다.

## 사이드바

에이전트 pane에는 herdr 사이드바 줄에 넣을 수 있는 토큰이 생깁니다.

| 토큰 | 예 | |
|---|---|---|
| `$usage_5h`, `$usage_week` | `82` | 사용 비율(색 규칙용) |
| `$usage_5h_reset`, `$usage_week_reset` | `↻3h30m`, `↻2d2h` | 리셋까지 남은 시간 |
| `$usage` | `5h 82% ↻3h30m · week 73% ↻2d2h` | 두 한도를 한 번에 |
| `$usage_account` | `me@example.com` | 로그인된 계정 |
| `$tool` | `Bash`, `notion:notion-search` | 작업 중 실행 중인 도구(모니터링 켰을 때) |
| `$skill` | `docx` | 마지막 프롬프트 이후 불러온 스킬(모니터링 켰을 때) |
| `$ctx` | `ctx 24%`(Codex), `ctx 92k`(Claude) | 컨텍스트 사용량(모니터링 켰을 때) |

좁은 사이드바용 배치 예시입니다. 사용량은 70%와 90%에서 색이 바뀝니다.

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "agent", "state_text", { token = "$tool", fg = "#f9e2af", dim = false }],
  [{ token = "$skill", fg = "#cba6f7", dim = false }, { token = "$ctx", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_5h", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_5h_reset", fg = "#cdd6f4", dim = false }],
  [{ token = "$usage_week", fg = "#a6e3a1", bold = true, dim = false, rules = [{ gt = 90, fg = "#f38ba8" }, { gt = 70, fg = "#f9e2af" }] }, { token = "$usage_week_reset", fg = "#cdd6f4", dim = false }],
  ["workspace", "tab"],
]
```

사용자 토큰은 스타일에 `dim = false`를 쓰지 않으면 흐리게 보입니다. 줄의 모든
토큰에 값이 없으면 그 줄은 사라집니다(예: Codex Pro에는 5시간 한도가 없음).
토큰은 에이전트 상태가 바뀔 때, Claude 훅이 돌 때, 그리고 모니터나 Agents 탭이
열려 있는 동안 몇 초마다 갱신됩니다. 갱신이 없으면 사용량 토큰은 15분, 활동
토큰은 5분 뒤에 사라지므로, 사이드바가 오래된 숫자를 현재 값처럼 보여주는 일은
없습니다.

## 설정값

모든 설정은 설정 탭에서 바꿉니다. 값은 `herdr plugin config-dir llm-usage`
폴더의 `config.json`에 저장됩니다.

| 키 | 기본값 | 의미 |
|---|---|---|
| `auto_switch` | `false` | Claude 계정 자동 전환 |
| `threshold` | `90` | 계정을 꽉 찬 것으로 보는 사용 비율 |
| `strategy` | `"best"` | `"best"`(남은 사용량 우선) 또는 `"soonest-reset"`(주간 리셋 임박 우선) |
| `model` | `null` | 함께 확인할 모델의 주간 한도, 예: `"fable"` |
| `agent_monitor` | `false` | 모니터, Agents 탭, 활동 토큰을 위해 트랜스크립트를 읽을지 |

**Check while Claude works**는 여기에 저장되지 않습니다. Claude Code의
`settings.json`에 이 플러그인의 훅이 있는지 여부가 곧 그 설정입니다.

## 읽고 쓰는 파일

| 경로 | 읽기 / 쓰기 | 내용 |
|---|---|---|
| macOS 키체인 `Claude Code-credentials`, `~/.claude/.credentials.json` | 읽기 | 사용량을 가져오기 위한 Claude 로그인 |
| `~/.codex/auth.json` | 읽기, Codex 전환 시 쓰기 | Codex 로그인 |
| `~/.codex/accounts/` | 쓰기 | 저장한 Codex 로그인(권한 600) |
| claude-swap 자체 저장소 | `cswap`을 통해 | 저장한 Claude 로그인 |
| `~/.claude/settings.json` | **Check while Claude works**를 켤 때만 쓰기 | 훅 두 개, 처음 한 번 `.llm-usage.bak` 백업 |
| `~/.claude/projects/`, `~/.codex/sessions/` | 읽기 | 세션 트랜스크립트, Claude 메모리 |
| 프로젝트의 `memory/`, `memory-archive/` | 메모리 정리에서만 쓰기 | 보관 이동, `MEMORY.md` 줄 |
| skills 폴더, `skills-disabled/` | 스킬 관리에서만 쓰기 | 끄기·켜기 이동 |
| `herdr plugin config-dir llm-usage` | 쓰기 | `config.json` |
| herdr 플러그인 상태 폴더 | 쓰기 | 사용량 캐시, 트랜스크립트 읽은 위치, 되돌리기 기록, 진단 기록 |

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 단축키가 안 먹거나 `prefix+?`에 안 보임 | **메뉴 → reload config**로 적용(`herdr server reload-config`가 아님) |
| 모니터 안의 키가 안 먹음 | `herdr plugin update` 후 모니터를 `q`로 닫고 다시 열기. 열려 있던 모니터는 예전 코드로 계속 돕니다 |
| 사이드바 숫자가 멈춤 | 설정 탭 → Background activity 확인. 긴 턴이 많으면 **Check while Claude works** 켜기 |
| "not signed in with a subscription" | CLI가 API 키를 쓰거나 로그아웃 상태. Claude Code에서 `/login` |
| 모니터나 Agents 탭에 "no transcript", "no session id" | `herdr integration install claude` / `codex` 후 새 세션 시작 |
| 모니터의 세션 옆에 "(guessed)" | herdr가 pane의 세션 ID를 모르기 때문에, 그 폴더의 가장 최근 트랜스크립트를 보여주는 중. 연동 설치 |
| Claude 전환을 쓸 수 없음 | claude-swap 설치. `cswap list`에 계정이 보여야 함 |
| Codex pane이 다시 이어지지 않음 | 알림에 이유가 나옴. pane은 셸에서 Codex를 실행한 상태여야 함 |
| 끝난 워크플로우가 계속 `◐` | 완료 알림이 플러그인이 모르는 형식이었음. 이슈로 알려주세요 |

`herdr plugin log list --plugin llm-usage`로 각 훅과 동작의 실행 기록, 종료 코드,
출력을 볼 수 있습니다.

## 자주 묻는 질문

**토큰을 쓰거나 에이전트를 느리게 하나요?**
아니요. 파일을 읽고 사용량 조회 주소에 묻기만 하며, 이 조회는 한도에 포함되지
않습니다. 에이전트 안에서 도는 것은 없습니다. 선택 사항인 Claude 훅도
백그라운드 명령을 최대 1분에 한 번 띄울 뿐입니다.

**Claude 계정을 바꿔도 실행 중인 세션이 정말 이어지나요?**
네. Claude Code는 요청할 때마다 로그인을 읽고, claude-swap은 Claude Code의
잠금을 잡은 상태에서 로그인을 바꿉니다. 대화, 컨텍스트, 실행 중인 도구는
그대로입니다.

**Codex는 왜 pane이 쉴 때까지 기다리나요?**
Codex는 시작할 때 한 번만 로그인을 읽습니다. 실행 중인 세션을 다른 로그인으로
옮기려면 종료하고 다시 이어가는 수밖에 없는데, 턴 도중에 하면 그 턴이
끊기기 때문입니다.

**구독을 바꿔 가며 써도 되나요?**
각 플랜의 약관을 확인하세요. 이 플러그인은 본인이 직접 로그인한 계정들 사이에서
바꿀 뿐, 계정을 공유하거나 합치지 않습니다.

**herdr 없이도 쓸 수 있나요?**
`python3 llm_usage.py status [--json]`은 어느 셸에서나 로그인된 계정의 사용량을
보여줍니다. 패널, 모니터, 사이드바는 herdr가 필요합니다.

**다른 사람과 함께 쓰는 프로젝트에서 메모리·스킬 관리를 써도 안전한가요?**
메모리는 본인 홈 폴더에 있으며 본인만 씁니다. 프로젝트 스킬을 끄면 프로젝트
안의 폴더가 옮겨지므로, git에 변경으로 나타나 커밋할지 되돌릴지 고를 수 있습니다.

## 제거

1. **Check while Claude works**가 켜져 있다면 먼저 설정 탭에서 끕니다. 그래야
   Claude Code의 `settings.json`에서 훅이 지워집니다.
2. `herdr plugin uninstall llm-usage`
3. `~/.config/herdr/config.toml`에서 `[[keys.command]]` 두 개와 `$usage…`,
   `$tool`, `$skill`, `$ctx` 토큰을 지웁니다.

저장한 Codex 로그인은 `~/.codex/accounts/`에, Claude 로그인은 claude-swap에 직접
지울 때까지 남습니다. 보관한 메모리와 꺼 둔 스킬도 옮겨 둔 자리에 그대로
있습니다.

## 개인정보와 데이터

- 모든 정보는 이 컴퓨터의 파일에서 읽습니다: CLI 로그인, 설정, 지침·메모리
  파일, 세션 트랜스크립트. 아래 사용량 조회 말고는 어디로도 보내지 않습니다.
- 사용량은 공식 CLI가 쓰는 비공개 주소에서 가져옵니다
  (`api.anthropic.com/api/oauth/usage`, `chatgpt.com/backend-api/wham/usage`).
  토큰은 읽기만 하고, 이 플러그인이 갱신하지 않습니다. 전환할 때의 토큰 처리는
  claude-swap이 직접 합니다.
- 트랜스크립트는 이어서 읽으며, 누적 값은 플러그인 상태 폴더에 저장합니다.

## 참고

- 사용량 조회 주소와 트랜스크립트 형식은 공개 API가 아니어서 바뀔 수 있습니다.
  읽지 못하는 부분은 이유를 보여주고, 나머지는 계속 동작합니다.
- Claude Code와 Codex 모두 여러 계정을 공식 지원하지 않습니다. 두 전환 방식
  모두 각 CLI 자체의 자격 증명 저장소를 그대로 씁니다.
- 플러그인은 herdr 환경의 계정을 씁니다. 그 환경에 `CLAUDE_CONFIG_DIR`와
  `CODEX_HOME`이 설정되어 있으면 따릅니다.

## 라이선스

[MIT](LICENSE)
