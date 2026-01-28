---
name: 分析并发问题与用户结果隔离设计
description: 用于分析当前项目在**无队列、无并发控制**情况下可能出现的问题，并给出**最小侵入式**的工程改造方案。
---

## description
用于分析当前项目在**无队列、无并发控制**情况下可能出现的问题，并给出**最小侵入式**的工程改造方案：
1. 识别多用户并发请求带来的风险点  
2. 判断哪些资源需要串行化、哪些可以并行  
3. 设计不引入新依赖的任务队列/调度方案（或最小实现）  
4. 新增用户维度，确保不同用户的分析结果、任务状态、数据目录完全隔离  

该 skill **只做分析与设计建议，不直接重构代码**，为后续工程实现提供清晰决策依据。

---

## input
- 项目当前目录结构
- 任务执行入口（如 start_run / execute_run）
- Run 目录组织方式
- 当前是否存在全局状态（session_state / 全局变量 / 单例对象）
- 当前 UI 是否支持多用户同时访问（如 Streamlit 公网部署）

---

## output
结构化分析结果 remembering **工程可落地性优先**：

```json
{
  "concurrency_risks": [
    {
      "risk": "并发任务互相覆盖",
      "cause": "run_id 或目录生成非线程安全",
      "impact": "分析结果错乱、数据丢失"
    }
  ],
  "shared_resources": [
    {
      "resource": "data/runs 目录",
      "type": "filesystem",
      "conflict_type": "write-write"
    }
  ],
  "queue_strategy": {
    "need_queue": true,
    "scope": "per-process",
    "recommended_model": "in-memory fifo",
    "why": "避免同时运行多个视频分析任务导致资源竞争"
  },
  "user_isolation_strategy": {
    "user_identity_source": "session / token / explicit user_id",
    "run_dir_naming": "data/runs/{user_id}/{task_name}__{run_id}",
    "ui_visibility": "用户只能看到自己的任务"
  },
  "non_goals": [
    "不引入 Redis / Celery",
    "不实现分布式队列"
  ]
}
```
````md
# skill: analyze-concurrency-and-user-isolation

## name
分析并发问题与用户结果隔离设计

## description
用于分析当前项目在**无队列、无并发控制**情况下可能出现的问题，并给出**最小侵入式**的工程改造方案：
1. 识别多用户并发请求带来的风险点  
2. 判断哪些资源需要串行化、哪些可以并行  
3. 设计不引入新依赖的任务队列/调度方案（或最小实现）  
4. 新增用户维度，确保不同用户的分析结果、任务状态、数据目录完全隔离  

该 skill **只做分析与设计建议，不直接重构代码**，为后续工程实现提供清晰决策依据。

---

## input
- 项目当前目录结构
- 任务执行入口（如 start_run / execute_run）
- Run 目录组织方式
- 当前是否存在全局状态（session_state / 全局变量 / 单例对象）
- 当前 UI 是否支持多用户同时访问（如 Streamlit 公网部署）

---

## output
结构化分析结果 remembering **工程可落地性优先**：

```json
{
  "concurrency_risks": [
    {
      "risk": "并发任务互相覆盖",
      "cause": "run_id 或目录生成非线程安全",
      "impact": "分析结果错乱、数据丢失"
    }
  ],
  "shared_resources": [
    {
      "resource": "data/runs 目录",
      "type": "filesystem",
      "conflict_type": "write-write"
    }
  ],
  "queue_strategy": {
    "need_queue": true,
    "scope": "per-process",
    "recommended_model": "in-memory fifo",
    "why": "避免同时运行多个视频分析任务导致资源竞争"
  },
  "user_isolation_strategy": {
    "user_identity_source": "session / token / explicit user_id",
    "run_dir_naming": "data/runs/{user_id}/{task_name}__{run_id}",
    "ui_visibility": "用户只能看到自己的任务"
  },
  "non_goals": [
    "不引入 Redis / Celery",
    "不实现分布式队列"
  ]
}
````

---

## analysis dimensions

### 1. 并发风险识别

Claude 必须逐项分析：

* 多用户同时点击「开始分析」
* 多线程 / 多进程同时写 Run 目录
* 全局变量、缓存、模型实例是否线程安全
* Streamlit rerun 机制是否放大并发问题

---

### 2. 队列是否必要（不是默认肯定）

Claude 必须判断：

* 是否允许同时跑多个分析
* 是否存在 CPU / GPU / IO 瓶颈
* 是否可以通过「串行化关键步骤」代替完整队列

explaining:

* 什么时候**不需要队列**
* 什么时候**必须引入队列或锁**

---

### 3. 队列设计约束（如需要）

如果判断需要队列，Claude 只能给出：

* **最小实现方案**
* 不引入新依赖
* 不改变现有 Pipeline API

示例方向（仅示意，不强制）：

* Python `queue.Queue`
* 单 worker 串行执行
* UI 只负责入队，不直接执行任务

---

### 4. 用户维度引入分析（重点）

Claude 必须明确回答：

* 当前项目是否“隐式单用户”
* 如果是，哪些地方默认假设了单用户：

  * Run 目录
  * 历史任务列表
  * session_state
* 用户身份从哪里来（不强制实现登录）：

  * session_id
  * cookie
  * 前端生成 user_id

并给出**不引入认证系统**的最小隔离方案。

---

## constraints

* 不写代码
* 不引入第三方组件
* 不设计复杂分布式系统
* 所有建议必须可以在当前技术栈内实现
* 优先保证：**正确性 > 吞吐量**

---

## when to use

当用户提出以下问题时，自动使用本 skill：

* “现在没有队列会不会有并发问题？”
* “多个人同时用会不会互相影响？”
* “怎么区分不同用户的分析结果？”
* “要不要上 Celery / Redis？”

---

## core principle

**宁可慢一点，也不要错。
宁可串行，也不要混乱。**
