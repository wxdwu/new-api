# Codex工具协议对照示例

2026-09-18。依据 `/Users/w/codex_0_2_6` 当前源码构造，未调用模型、未运行Rust转换器、不是历史trace。模型名称为占位符；工具说明和参数经过缩减，kb.search是假设注册的业务工具，不是Codex固定内置工具。两份GPT output是可选响应示例，不是模型必然输出。Chat输出文件表示流式片段聚合后的内容，不是stream=true时的单个原始HTTP响应。

- 01：包含五类ToolSpec的Responses请求；custom有exec和apply_patch两个定义。
- 02：根据当前内核Chat转换规则推导，仅留下顶层exec_command。切换模型名需要由provider/model配置完成；转换器自身不会将GPT名字自动改为DeepSeek。
- 03：若转换前只有namespace/custom/web_search/tool_search等非顶层function，过滤后tools及tool_choice均被省略。
- 04：GPT使用custom exec编排命令工具与知识库函数的可能响应；需对应模型服务和Code Mode运行时支持。
- 05：GPT直接调用命名空间函数的另一种可能响应，仍是function_call，额外包含namespace。
- 06：DeepSeek Chat的一次函数调用示例；也可能返回普通文本，不能预言模型必然调用。
- 07：06经过内核桥接后的统一FunctionCall，只恢复函数名、参数及调用ID，不恢复custom或namespace能力。

源码依据：codex-api/src/endpoint/chat_completions.rs:318、470、657；core/src/tools/spec_plan.rs:539、434；core/src/client.rs:1613。Chat转换器不按GPT或DeepSeek品牌分支：任何模型经过相同转换都会遭遇同样定义过滤。

核对说明：仅核对JSON语法和人工推导的结构，没有进行API兼容测试或历史性能复现。
