# XECKernelPro 模块仓库

XECKernelPro（KernelSU 分支）管理器的**默认模块仓库**。管理器读的就是本仓库根目录的
[`modules.json`](modules.json)，格式与官方 `modules.kernelsu.org/modules.json` **完全同 schema**。

## 管理器里可用的地址

- jsDelivr（国内一般可达，管理器默认走这条）：
  `https://cdn.jsdelivr.net/gh/byBOOK10086/XECKernelPro-Modules@main/modules.json`
- 原始文件（jsDelivr 抽风时的兜底）：
  `https://raw.githubusercontent.com/byBOOK10086/XECKernelPro-Modules/main/modules.json`
- 官方源（管理器里作为最后兜底）：
  `https://modules.kernelsu.org/modules.json`

管理器里「模块仓库」页右上角的云图标可以改地址、一键切默认/官方，列表上方常显当前实际生效的源。

## 用户怎么上传 / 登记模块

开一个 [issue（上传 / 登记模块）](../../issues/new?template=upload-module.yml)，两种方式任选：

| 方式 | 你要做的 | zip 托管在哪 |
|---|---|---|
| 一、有自己的 GitHub 仓库 | 把模块 zip 发到你自己仓库的 Release，issue 里填 `owner/repo` | 你自己的 Release |
| 二、只有 zip 直链 | 把 zip 传到任意可直链下载的地方，issue 里填直链 | 本仓库的 Release（机器人转存） |

两种情况都会：校验 zip 里的 `module.prop`（`id` 合法性 / `name` / `version` / `versionCode`）→
更新索引 → 回帖并自动关闭 issue。校验不通过**不会**写进索引，原因会原样回帖。

## 索引是怎么生成的

- [`sources.json`](sources.json)：登记过的「作者自己的仓库」列表 `{id, repo}`。
- [`hosted.json`](hosted.json)：转存到本仓库 Release 的 zip 记录 `{id, tag, asset, versionCode, sha256, size}`。
- [`scripts/build_index.py`](scripts/build_index.py)：拉每个模块**最新 Release** 的 zip，
  **以 zip 内 `module.prop` 的实际内容为准**写出 `modules.json`（避免索引与模块本体不一致）。
- 触发：`sources.json` / `hosted.json` 变更、每 6 小时的定时任务、或手动
  [Rebuild module index](../../actions/workflows/rebuild-index.yml)。

## 许可

本仓库只存索引与（经作者许可转存的）模块 zip；模块本身的许可证由各自作者决定。
