# Parse source as data. Never invoke workflow commands.
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
while ($null -ne ($inputLine = [Console]::ReadLine())) {
    try {
        $source = ConvertFrom-Json -InputObject $inputLine
        $tokens = $null
        $parseErrors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
        if ($parseErrors.Count -gt 0) {
            @{error='PowerShell parse error';ranges=@()} | ConvertTo-Json -Compress -Depth 5
            continue
        }
        $ranges = @($tokens | Where-Object Kind -EQ 'Comment' | ForEach-Object {
            ,@($_.Extent.StartLineNumber, $_.Extent.StartColumnNumber, $_.Extent.EndLineNumber, $_.Extent.EndColumnNumber)
        })
        @{ranges=$ranges} | ConvertTo-Json -Compress -Depth 5
    } catch {
        @{error=$_.Exception.Message;ranges=@()} | ConvertTo-Json -Compress -Depth 5
    }
}
