# Employee 表单界面自定义

本文件记录 HRMS 员工表单的界面设置、影响范围、验证方法和持久化方式。

## 当前设置

| DocType | 字段 | 属性 | 值 | Property Setter 名称 | 效果 |
|---|---|---|---|---|---|
| Employee | `middle_name` | `hidden` | `1` | `Employee-middle_name-hidden` | 隐藏“中间名” |
| Employee | `salutation` | `hidden` | `1` | `Employee-salutation-hidden` | 隐藏“称谓” |
| Employee | `last_name` | `hidden` | `1` | `Employee-last_name-hidden` | 隐藏“姓” |
| Employee | DocType 级 | `show_title_field_in_link` | `1` | `Employee-main-show_title_field_in_link` | 指向 Employee 的 Link 字段优先显示 `employee_name` |

这些设置只改变表单显示：

- 不删除字段。
- 不修改员工数据。
- 不改变 `reports_to` 等 Link 字段实际存储的 docname。例如“上级主管”仍存储 `HR-EMP-00003`，界面显示“骆秀韬”。
- `show_title_field_in_link` 是 DocType 级设置，会影响所有指向 Employee 的 Link 字段，而不只影响 `reports_to`。

## 查看当前设置

```bash
docker exec -w /home/frappe/frappe-bench docker-frappe-1 \
  bench --site hrms.localhost execute 'exec("import json; fields=[\"middle_name\",\"salutation\",\"last_name\"]; ps=frappe.get_all(\"Property Setter\", filters={\"doc_type\":\"Employee\"}, fields=[\"name\",\"doctype_or_field\",\"field_name\",\"property\",\"value\"]); m=frappe.get_meta(\"Employee\"); print(json.dumps({\"show_title_field_in_link\":m.show_title_field_in_link,\"hidden\":{f:bool(m.get_field(f).hidden) for f in fields},\"property_setters\":ps},ensure_ascii=False))")'
```

预期结果：

- `show_title_field_in_link` 为 `1`。
- `middle_name`、`salutation`、`last_name` 的 `hidden` 均为 `true`。
- 存在上表列出的 4 条 Property Setter。

## 正常重启与容器重建

Property Setter 是 HRMS 数据库记录。只要数据库卷保留，正常重启服务、重建容器或执行 `bench clear-cache` 都不会丢失设置。

以下情况会丢失数据库中的设置：

- 删除数据库卷。
- 删除并重新创建站点。
- 迁移到新的空数据库。

这些场景需要通过 Fixtures 或迁移脚本恢复。

## Docker 启动时自动应用

当前 Docker 环境已经使用幂等启动脚本自动应用上述设置，不依赖手动执行 Customize Form。

涉及文件：

```text
third-party/hrms/docker/init.sh
third-party/hrms/docker/ensure_employee_form_customizations.py
```

`docker-compose.yml` 每次启动 Frappe 容器时都会执行 `bash /workspace/init.sh`。`init.sh` 在安装 HRMS 后、启动 Bench 前调用：

```bash
bench --site hrms.localhost execute "exec(open('/workspace/ensure_employee_form_customizations.py').read(), globals())"
```

脚本行为：

- 检查 4 条 Property Setter。
- 缺失时创建。
- 值被改错时修正。
- 已正确存在时不重复创建。
- 发现同一条设置存在重复记录时停止并报错，避免静默覆盖。
- 完成后清理 Frappe 缓存。

脚本只修改 Property Setter，不读取或修改员工业务数据。

### 手动验证启动脚本

```bash
docker exec -w /home/frappe/frappe-bench docker-frappe-1 \
  bench --site hrms.localhost execute "exec(open('/workspace/ensure_employee_form_customizations.py').read(), globals())"
```

正常情况下，首次执行输出 `created`，后续执行输出 `unchanged`。如果设置被改错，则会输出 `updated` 并自动修正。

## 使用 Fixtures 持久化

推荐把 Property Setter 导出为 Fixture JSON，并随 HRMS 代码提交。这样新站点执行 `bench migrate` 时可以自动恢复。

### 1. 配置 Fixtures

在 `hrms/hooks.py` 中添加：

```python
fixtures = [
    {
        "dt": "Property Setter",
        "filters": [
            [
                "name",
                "in",
                [
                    "Employee-middle_name-hidden",
                    "Employee-salutation-hidden",
                    "Employee-last_name-hidden",
                    "Employee-main-show_title_field_in_link",
                ],
            ]
        ],
    }
]
```

如果站点中还存在其他 Fixtures，应把该条目合并到现有 `fixtures` 列表中，不要覆盖已有配置。

### 2. 导出 Fixture

```bash
docker exec -w /home/frappe/frappe-bench docker-frappe-1 \
  bench --site hrms.localhost export-fixtures
```

导出文件位于宿主仓库：

```text
third-party/hrms/hrms/fixtures/property_setter.json
```

将 `hooks.py` 和 `fixtures/property_setter.json` 一起提交到 HRMS 代码仓库。

### 3. 在目标站点恢复

```bash
bench --site <site> migrate
```

迁移完成后执行：

```bash
bench --site <site> clear-cache
```

### 4. 后续修改

通过 Customize Form 或 Property Setter 修改设置后，需要重新执行：

```bash
bench --site <site> export-fixtures
```

然后提交更新后的 Fixture JSON。

如果 Property Setter 因同名记录而产生带编号的名称，应同步更新 `hooks.py` 中的 Fixture 名称列表。

## 回滚

### 仅恢复显示

在 Frappe 的 **Customize Form** 中取消对应设置，或删除上述 4 条 Property Setter，然后执行：

```bash
bench --site <site> clear-cache
```

### 代码化环境

从 Fixture 文件和应用配置中移除对应记录，再在目标站点执行 `bench migrate`。如果目标站点仍保留旧 Property Setter，需要单独删除数据库记录后才能完全恢复默认显示。
