# AI OS test workbench. Reports what the user did as JSON lines on stdout, which only the
# benchmark process can read, so the outcome cannot be faked by scripts writing files.
# Launched by benchmark/workbench.py, which prepends `$Scenario = '...'`.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Windows.Forms.Application]::EnableVisualStyles()

function Emit($data) {
    [Console]::Out.WriteLine(($data | ConvertTo-Json -Compress))
    [Console]::Out.Flush()
}

function New-Control($type, $props) {
    $control = New-Object "Windows.Forms.$type"
    foreach ($key in $props.Keys) { $control.$key = $props[$key] }
    $control
}

$form = New-Control Form @{
    Text = 'AI OS 测试工作台'; Size = New-Object Drawing.Size(540, 470)
    StartPosition = 'CenterScreen'; Font = New-Object Drawing.Font('Microsoft YaHei UI', 10)
}

switch ($Scenario) {
    'dialog' {
        $status = New-Control Label @{ Text = '记录：128 条'; Location = '30,30'; AutoSize = $true }
        $button = New-Control Button @{ Text = '清空记录'; Location = '30,80'; Size = '140,40' }
        $button.Add_Click({
            $answer = [Windows.Forms.MessageBox]::Show($form, '确定要清空全部 128 条记录吗？此操作无法撤销。',
                '确认清空', 'YesNo', 'Warning')
            if ($answer -eq 'Yes') {
                $status.Text = '记录：0 条（已清空）'
                Emit @{ event = 'cleared' }
            } else {
                Emit @{ event = 'cancelled' }
            }
        })
        $form.Controls.AddRange(@($status, $button))
    }

    'tabs_form' {
        $tabs = New-Control TabControl @{ Location = '20,20'; Size = '480,300' }
        $basic = New-Control TabPage @{ Text = '基本' }
        $advanced = New-Control TabPage @{ Text = '高级' }

        $basic.Controls.Add((New-Control Label @{ Text = '用户名'; Location = '20,30'; AutoSize = $true }))
        $user = New-Control TextBox @{ Location = '120,27'; Width = 220; AccessibleName = '用户名' }
        $basic.Controls.Add((New-Control Label @{ Text = '角色'; Location = '20,80'; AutoSize = $true }))
        $role = New-Control ComboBox @{ Location = '120,77'; Width = 220; DropDownStyle = 'DropDownList'; AccessibleName = '角色' }
        [void]$role.Items.AddRange(@('访客', '编辑', '管理员'))
        $role.SelectedIndex = 0
        $basic.Controls.AddRange(@($user, $role))

        $twofa = New-Control CheckBox @{ Text = '启用双重验证'; Location = '20,30'; AutoSize = $true }
        $advanced.Controls.Add((New-Control Label @{ Text = '超时（分钟）'; Location = '20,80'; AutoSize = $true }))
        $timeout = New-Control NumericUpDown @{ Location = '160,77'; Minimum = 1; Maximum = 120; Value = 10; AccessibleName = '超时（分钟）' }
        $advanced.Controls.AddRange(@($twofa, $timeout))

        $tabs.TabPages.AddRange(@($basic, $advanced))
        $saved = New-Control Label @{ Text = ''; Location = '160,345'; AutoSize = $true }
        $save = New-Control Button @{ Text = '保存'; Location = '20,335'; Size = '120,40' }
        $save.Add_Click({
            $saved.Text = '已保存'
            Emit @{ event = 'saved'; user = $user.Text; role = [string]$role.SelectedItem
                    twofa = $twofa.Checked; timeout = [int]$timeout.Value }
        })
        $form.Controls.AddRange(@($tabs, $save, $saved))
    }

    'long_list' {
        $list = New-Control ListBox @{ Location = '20,20'; Size = '480,330'; AccessibleName = '项目列表' }
        [void]$list.Items.AddRange((1..300 | ForEach-Object { '项目 {0:D3}' -f $_ }))
        $open = New-Control Button @{ Text = '打开'; Location = '20,365'; Size = '120,40' }
        $open.Add_Click({
            if ($null -eq $list.SelectedItem) {
                [void][Windows.Forms.MessageBox]::Show($form, '请先选择一个项目', '提示')
                return
            }
            $item = [string]$list.SelectedItem
            $detail = New-Control Form @{
                Text = "$item 详情"; Size = New-Object Drawing.Size(360, 220); StartPosition = 'CenterParent'
                Font = $form.Font
            }
            $detail.Controls.Add((New-Control Label @{ Text = "$item：状态 未完成"; Location = '20,30'; AutoSize = $true }))
            $done = New-Control Button @{ Text = '标记完成'; Location = '20,90'; Size = '140,40' }
            $done.Add_Click({
                Emit @{ event = 'done'; item = $item }
                $detail.Close()
            }.GetNewClosure())
            $detail.Controls.Add($done)
            [void]$detail.ShowDialog($form)
        })
        $form.Controls.AddRange(@($list, $open))
    }
}

Emit @{ event = 'ready' }
[void]$form.ShowDialog()
Emit @{ event = 'closed' }
