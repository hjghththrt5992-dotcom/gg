# 低成本知识库训练模型

把知识库教给一个开源小模型（Qwen2.5 0.5B / 1.5B），训练完成后模型不查任何资料，直接回答知识库里的问题。
普通电脑就能训练，不需要显卡，不调用任何收费接口。项目自带一个知识库（13 篇 AI/大模型基础知识），不需要准备任何资料。

```bash
bash llm/setup.sh                 # 第一次：创建虚拟环境 .venv 并安装依赖
source .venv/bin/activate         # 每次使用前：激活虚拟环境
python llm/main.py check          # 检测配置，推荐模型大小，估算训练时间
python llm/main.py download       # 下载底座模型（国内自动走镜像）
python llm/main.py auto           # 一键生成训练数据并训练
python llm/main.py chat           # 用训练好的模型问答
```

原理、分步运行、评测、配置要求和常见问题见 [llm/README.md](llm/README.md)。

## 许可证

[AGPL-3.0](LICENSE)
