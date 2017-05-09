###################
# mdiag.ps1 - Windows Diagnostic Script for MongoDB

[CmdletBinding()]

param(
   [string] $SFSCTicketNumber,
   [switch] $DoNotElevate,
   [switch] $Counters,
   [int]    $Interval = 15,      ## Time in seconds between samples
   [int]    $Samples  = 40       ## Number of times Get-Counter will collect a sample of a counter
)

#======================================================================================================================
function Main
#======================================================================================================================
{
   # ------------------------- #
   # FingerprintOutputDocument #
   # ------------------------- #
   
   # this is the output field of the fingerprint probe
   # should be kept at the top of the file for ease of access
   
   Set-Variable FingerprintOutputDocument -option Constant @{
      os = (Get-WmiObject Win32_OperatingSystem).Caption;
      shell = "PowerShell $($PSVersionTable.PSVersion)";
      script = "mdiag";
      version = "1.7.13";
      revdate = "2017-05-09";
   }
   
   Setup-Environment
   
   $script:FilesToCompress = @($script:DiagFile)
         
   # Only write to output file once all probes have completed
   $probeOutput = Run-Probes 
   $probeOutput | Out-File $script:DiagFile
   
   Write-Host "Finished.`r`n"

   try
   {      
      $zipFile = [IO.Path]::Combine([IO.Path]::GetDirectoryName($script:DiagFile), [IO.Path]::GetFileNameWithoutExtension($script:DiagFile) + '.zip')    
      Compress-Files $zipFile $script:FilesToCompress
      
      $script:FilesToCompress | % {
         if ([IO.Path]::GetDirectoryName($_) -eq [IO.Path]::GetTempPath().TrimEnd('\') -or $_ -eq $script:DiagFile)
         {
            Remove-Item -Force $_ -ErrorAction SilentlyContinue
            return
         }

         Write-Verbose "Attempt to delete a file not located in temporary path - $_"         
      }
   }
   catch
   {
      Write-Warning "Unable to compress results file : $($_.Exception.Message)"
      $zipFile = $script:DiagFile
   }
   
   if ($SFSCTicketNumber)
   {
      Write-Host "Please attach '$zipFile' to MongoDB Technical Support case $SFSCTicketNumber.`r`n"
   }

   Write-Host "Press any key to continue ..."
   $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") | Out-Null
   Write-Host
}

#======================================================================================================================
# Public API
#======================================================================================================================
# * The functions in this section constitute the public API of mdiag.ps1
# * Use these in the script portion below. Please don't directly call other functions; the
#   interfaces there are not guaranteed to be constant between versions of this script.
#======================================================================================================================

#======================================================================================================================
# Run probe specified in $doc
#======================================================================================================================
# $doc should be a hashtable with the following: 
#
#  @{      name    = "section title";
#          cmd     = "invoke-cmd";
#    (opt) alt     = "alternative-invoke-cmd";
#  }
#======================================================================================================================
function probe( $doc ) 
#======================================================================================================================
{
   if (-not $doc.name -or -not $doc.cmd) 
   {
      throw "assert: malformed section descriptor document, must have 'name' and 'cmd' members at least"
   }

   Write-Verbose "Gathering section [$($doc.name)]"

   # run the probe once
   $cmdobj = Run-Command $doc.cmd
   
   if (-not $cmdobj.ok) 
   {
      if ($doc.alt) 
      {
         # preferred cmd failed and we have a fallback, so try that
         Write-Verbose " | Preference attempt failed, but have a fallback to try..."

         $fbcobj = Run-Command $doc.alt

         if ($fbcobj.ok) 
         {
            Write-Verbose " | ... which succeeded!"
         }

         $fbcobj.fallback_from = @{
            command = $cmdobj.command;
            error = $cmdobj.error;
         }
         
         $cmdobj = $fbcobj
      }
   }

   Emit-Document $doc.name $cmdobj

   Write-Verbose "Finished with section [$($doc.name)]. Closing`r`n"
}

#======================================================================================================================
# Generic internal functions
#======================================================================================================================
# Please don't call these in the script portion of the code. The API here will never freeze.
#======================================================================================================================
function Escape-JSON($String) 
#======================================================================================================================
{
   # order is important, ie \\ should go before \'
   $String = $String.Replace('\','\\')
   $String = $String.Replace('"','\"')
   
   # Does not need to be escaped
   # $String = $String.Replace("'","\'")

   # Does not need to be escaped for MongoDB
   # $result = $result.Replace("&",'\u0026')

   $String = $String.Replace("`n",'\n')
   $String = $String.Replace("`r",'\r')
   $String = $String.Replace("`t",'\t')
   $String = $String.Replace("`b",'\b')
   $String = $String.Replace("`f",'\f')

   $String
}

#======================================================================================================================
function _tojson_string( $v ) 
#======================================================================================================================
{
   "`"$(Escape-JSON $v)`""
}

#======================================================================================================================
# provide a JSON encoded date
#======================================================================================================================
function _tojson_date( $v ) 
#======================================================================================================================
{
   "{{ `"`$date`": `"{0}`" }}" -f $( _iso8601_string $v );
}

#======================================================================================================================
# pipe in a stream of @{Name="",Value=*} for the properties of the object
#======================================================================================================================
function _tojson_object( $indent ) 
#======================================================================================================================
{
   $ret = $( $input | ForEach-Object { "{0}`t`"{1}`": {2}," -f $indent, $_.Name, $( _tojson_value $( $indent + "`t" ) $_.Value ) } | Out-String )
   "{{`r`n{0}`r`n{1}}}" -f $ret.Trim("`r`n,"), $indent
}

#======================================================================================================================
# pipe in a stream of objects for the elements of the array
#======================================================================================================================
function _tojson_array( $indent ) 
#======================================================================================================================
{
   if( @($input).Count -eq 0 ) {
      "[]"
   }
   else {
      $input.Reset()
      $ret = $( $input | ForEach-Object { "{0}`t{1}," -f $indent, $( _tojson_value $( $indent + "`t" ) $_ ) } | Out-String )
      "[`r`n{0}`r`n{1}]" -f $ret.Trim("`r`n,"), $indent
   }
}

#======================================================================================================================
# JSON encode object value, not using ConvertTo-JSON due to TSPROJ-476
#======================================================================================================================
function _tojson_value( $indent, $obj ) 
#======================================================================================================================
{
   if ($obj -eq $null)
   {
      return "null"
   }
   
   if ($indent.Length -gt 4) 
   {
      # aborting recursion due to object depth; summarize the current object
      # if it's an array we put in the count, anything else ToString()
      if ($obj.GetType().IsArray)
      {
         return $obj.Length
      }
      else 
      {
         return (_tojson_string $obj.ToString())
      }
   }

   switch ($obj.GetType()) 
   {
      { $_.IsArray } {
         $obj | _tojson_array $indent
         break
      }
         
      { $_.IsEnum -or "String","Char","TimeSpan" -contains $_.Name } {
         _tojson_string $obj.ToString()
         break
      }
            
      { $_.Name -eq "DateTime" } {
         _tojson_date $obj
         break
      }
      
      { $_.Name -eq "Boolean" } {
         @('false','true')[$obj -eq $true]
         break
      }
      
      { "Uint16","Int16","Int32","UInt32","Int64","UInt64","Double","Byte","UIntPtr","IntPtr" -contains $_.Name } {
         # symbolic or integrals, write plainly
         $obj.ToString()
         break
      }

      { $_.GetInterfaces() -contains [Collections.IDictionary] -or $_.GetInterfaces() -contains [Collections.IList] } {
         if ($_.GetInterfaces() -contains [Collections.ICollection] -and -not $obj.Count)
         {
            "null"
            break
         }
         
         if ($_.GetInterfaces() -contains [Collections.IEnumerable])
         {
            $props = $obj.GetEnumerator()
         }
         else
         {
            $props = $obj
         }
         
         $props | Select @{ Name = 'Name' ; Expression = { Escape-JSON $_.Key }}, Value | _tojson_object $indent
         break
      }
      
      default {
         if ($_.IsClass) 
         {
            $obj.psobject.properties.GetEnumerator() | _tojson_object $indent
         }
         else 
         {
            # dunno, just represent as simple as possible
            _tojson_string $obj.ToString()
         }
      }
   }
}

#======================================================================================================================
# (internal) emit to file the JSON encoding of supplied obj using whatever means is available
#======================================================================================================================
function _tojson( $obj ) 
#======================================================================================================================
{
   # TSPROJ-476 ConvertTo-JSON dies on some data eg: Get-NetFirewallRule | ConvertTo-Json = "The converted JSON string is in bad format."
   # using internal only now, probably forever
   return _tojson_value "" $obj;
}

#======================================================================================================================
# get current (or supplied) DateTime formatted as ISO-8601 localtime (with TZ indicator)
#======================================================================================================================
function _iso8601_string( [DateTime] $date ) 
#======================================================================================================================
{
   # TSPROJ-386 timestamp formats
   # turns out the "-s" format of windows is ISO-8601 with the TZ indicator stripped off (it's in localtime)
   # so... we just need to append the TZ that was used in the conversion thusly:
   if (-not $date) 
   {
      $date = Get-Date
   }
   
   if (-not $script:tzstring) 
   {
      # [System.TimeZoneInfo]::Local.BaseUtcOffset; <- should use this "whenever possible" which is .NET 3.5+
      # using the legacy method instead for maximum compatibility
      $tzo = [TimeZone]::CurrentTimeZone.GetUtcOffset($date)
      $script:tzstring = "{0}{1:00}{2:00}" -f @("+","")[$tzo.Hours -lt 0], $tzo.Hours, $tzo.Minutes
   }
   
   # ISO-8601
   return "{0}.{1:000}{2}" -f (Get-Date -Format s -Date $date), $date.Millisecond, $script:tzstring
}

#======================================================================================================================
# Hashing function used by mongod configuration file redaction
#======================================================================================================================
function Hash-SHA256($StringToHash)
#======================================================================================================================
{
   $hasher = New-Object Security.Cryptography.SHA256Managed
   
   $result = ''
   $hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($StringToHash)) | % { $result += ([byte] $_).ToString('X2') }
   $result
}

#======================================================================================================================
# Return redacted string representation of mongod configuration file
#======================================================================================================================
function Redact-ConfigFile($FilePath)
#======================================================================================================================
{
   $optionsToRedact = @('\bquery(?:User|Password):[\s]*([^\s]*)', `
                        '\bservers:[\s]*([^\s]*)'
                      )

   Get-Content $FilePath -ErrorAction Stop | % {
      if ([String]::IsNullOrEmpty($_))
      {
         return ""
      }
      
      $currentLine = $_
      $matchFound = $false
         
      $optionsToRedact | % {
         if ($currentLine -match $_)
         {
            $currentLine.Replace($Matches[1], "<redacted sha256 $(Hash-SHA256 $Matches[1])>")
            $matchFound = $true
         }
      }
      
      if (-not $matchFound)
      {
         $currentLine
      }
   } 
}

#======================================================================================================================
# Produces Json document that contains probe results
#======================================================================================================================
function Emit-Document($Section, $CmdObj)
#======================================================================================================================
{
   $CmdObj.ref = $script:SFSCTicketNumber
   $CmdObj.tag = $script:RunDate
   $CmdObj.section = $section
   $CmdObj.ts = Get-Date
   
   try 
   {
      return (_tojson $CmdObj)
   }
   catch 
   {
      $CmdObj.output = ""
      $CmdObj.error = "output conversion to JSON failed : $($_.Exception.Message)"
      $CmdObj.ok = $false

      # give it another shot without the output, just let it die if it still has an issue
      return (_tojson $CmdObj)
   }
}

#======================================================================================================================
# Wrapper for running the command that makes up a probe
#======================================================================================================================
function Run-Command($CommandString)
#======================================================================================================================
{
   if (-not $CommandString)
   {
      throw (New-Object System.ArgumentNullException("CommandString"))
   }

   # selecting only the first arg in the stream now due to possible mongoimport killers like ' " etc (which come out as \u00XX)
   $result = [Collections.SortedList] @{ command = $CommandString.Split("|")[0].Split("`n")[0].Trim() }
   
   try
   {
      Write-Debug "Running command:`r`n$CommandString"
      $result.output = Invoke-Command -ScriptBlock ([ScriptBlock]::Create($CommandString))
      Write-Debug "Result:`r`n$($result.output | Out-String)"
      $result.ok = $true
   }
   catch
   {
      Write-Verbose $_.Exception.Message
      $result.ok = $false
      $result.error = $_.Exception.Message
   }
   
   $result
}

#======================================================================================================================
# Get list of probes and run them
#======================================================================================================================
function Run-Probes
#======================================================================================================================
{
   Write-Verbose "Running Probes"
   $script:RunDate = Get-Date

   $sb = New-Object System.Text.StringBuilder

   $sb.Append('[') | Out-Null
   $sb.Append((Emit-Document "fingerprint" @{ command = $false; ok = $true; output = $FingerprintOutputDocument; })) | Out-Null

   ($probes = Get-Probes) | % {
      $probeCount++
      Write-Progress "Gathering diagnostic information ($probeCount/$($probes.Length))" -Id 1 -Status $_.name -PercentComplete (100 / $probes.Length * $probeCount)      
      $sb.Append(",`r`n$(probe $_)") | Out-Null
   }
   
   Write-Progress "Gathering diagnostic information" -Id 1 -Status "Done" -Completed
   
   if ($script:Counters)
   {
      # Hide progress bar as probe writes directly to console
      $setting = $script:ProgressPreference
      $script:ProgressPreference = 'SilentlyContinue'
      
      $result = probe @{ name = "performance-counters";
                         cmd = "Collect-PerformanceCounters $script:Samples $script:Interval"
                      }
      
      $sb.Append(",`r`n$result") | Out-Null
      
      $script:ProgressPreference = $setting
   }

   $sb.Append("]") | Out-Null
   
   $sb.ToString() 
}

#======================================================================================================================
function Compress-Files($ZipFile, [String[]] $Files)
#======================================================================================================================
{
   Set-Content $ZipFile ( [byte[]] @( 80, 75, 5, 6 + (, 0 * 18 ) ) ) -Force -Encoding byte
   
   $zipFolder = (New-Object -Com Shell.Application).NameSpace($ZipFile)

   $Files | % {
      if (-not (Test-Path $_)) 
      {
         return
      }
      
      $shortFileName = [IO.Path]::GetFileName($_)
      $zipFolder.CopyHere($_)
      
      Write-Verbose "Compressing $shortFileName" 
      
      while (-not $zipFolder.Items().Item($shortFileName)) 
      {
         Start-Sleep -m 500
      }
   }
}

#======================================================================================================================
# Extract properties from WMI class
#======================================================================================================================
function Get-WmiClassProperties($WmiClass, $Filter)
#======================================================================================================================
{  
   if (-not (Get-WmiObject -Class $WmiClass -List))
   {
      throw "WMI class $WmiClass does not exist"
   }
   
   if ($Filter)
   {
      $class = Get-WmiObject $WmiClass -Filter $Filter -ErrorAction Stop
   }
   else
   {
      $class = Get-WmiObject $WmiClass -ErrorAction Stop
   }

   if (-not $class)
   {
      return $null
   }
      
   if ($class -is [Collections.IEnumerable])
   {
      $props = $class.GetEnumerator()
   }
   else
   {
      $props = $class
   }
   
   $props | % { 
      $result = @{}
      $class = $_
      
      $_ | Get-Member | ? { $_.MemberType -eq 'Property' -and -not $_.Name.StartsWith('__') } | % { 
         $result.Add($_.Name, "$($class.($_.Name))")
      }
      
      $result
   }
}

#======================================================================================================================
function Get-RegistryValues($RegPath)
#======================================================================================================================
{
   if (-not (Test-Path $RegPath -ErrorAction SilentlyContinue))
   {
      return
   }
   
   # First we need to check for any values under the supplied key
   if ($regKey = Get-ItemProperty $RegPath -ErrorAction SilentlyContinue)
   {
      $outerResult = New-Object Collections.Specialized.OrderedDictionary
      $outerResult.Add("Key", $regKey.PSPath.Split(':')[2])
      $outerResult.Add('LastModified', (Get-RegistryLastWriteTime $RegPath))
      
      $innerResult = New-Object Collections.Specialized.OrderedDictionary
      
      $regKeys = $regKey.PSObject.Properties | ? { ('PSDrive','PSPath','PSChildName','PSParentPath','PSProvider' -notcontains $_.Name) }
      $regKeys | Select Name, TypeNameOfValue, Value | Sort-Object Name | % { 
         if ($_.TypeNameOfValue -eq 'System.String')
         {
            $innerResult.Add($_.Name, ([String] $_.Value).TrimEnd("`0"))
         }
         else
         {
            $innerResult.Add($_.Name, $_.Value)
         }      
      }
      
      $outerResult.Add('Values', $innerResult)
      $outerResult
   }
   
   # Then we check for any sub keys and recurse them
   Get-ChildItem $RegPath -Recurse | % {
      $reg = $_
   
      $outerResult = New-Object Collections.Specialized.OrderedDictionary
      $outerResult.Add("Key", $reg.PSPath.Split(':')[2])
      $outerResult.Add('LastModified', (Get-RegistryLastWriteTime $reg.PSPath))

      $innerResult = New-Object Collections.Specialized.OrderedDictionary
      
      $reg.Property | % {
         if ($reg.GetValue($_) -is 'System.String')
         {
            $innerResult.Add($_, ([String] $reg.GetValue($_)).TrimEnd("`0"))
         }
         else
         {
            $innerResult.Add($_, $reg.GetValue($_))
         }      
      }
      
      $outerResult.Add('Values', $innerResult)
      $outerResult
   }
}

#======================================================================================================================
# Ensure PowerShell environment is initialised, take care of elevation if necessary
#======================================================================================================================
function Setup-Environment
#======================================================================================================================
{  
   $FingerprintOutputDocument.GetEnumerator() | % { Write-Verbose "$($_.Key) = $($_.Value)" }
   Write-Verbose "Checking permissions"

   if ($PSVersionTable.PSVersion -lt '2.0')
   {
      Write-Warning "This script requires PowerShell 2.0 or greater"
      Exit
   }
   
   # check if we are admin
   if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
   {
      Write-Verbose "Script is not run with administrative user"

      # see if we can elevate
      if ($DoNotElevate)
      {
         # user expressly asked to avoid privilege elevation (or the script has already been here)
         Write-Verbose "Instructed not to elevate or we're in a hall of mirrors.. aborting elevation"
         Write-Warning "Not running as administrative user but instructed not to elevate. Some health checks may fail."
      }
      elseif (([int] (Get-WmiObject Win32_OperatingSystem).BuildNumber) -ge 6000) 
      {
         Write-Verbose "Found UAC-enabled system. Attempting to elevate ..."

         # when elevating we need to twiddle the command-line a little to be more robust
         $CommandLine = @('-ExecutionPolicy', 'Unrestricted')
                  
         if ($DebugPreference -eq 'Continue')
         {
            $CommandLine += '-NoExit'
         }
         
         $CommandLine += @('-File', "`"$($script:MyInvocation.MyCommand.Definition)`"")

         # do not attempt elevation again on relaunch, in case some bizarro world DC policy causes Runas to fake us out (because that would cause an infinite loop)
         $CommandLine += '-DoNotElevate'

         $script:PSBoundParameters.Keys | % {
            $CommandLine += "-$_"
            if ($script:PSBoundParameters[$_] -isnot [Management.Automation.SwitchParameter]) 
            {
               $CommandLine += ([string] $script:PSBoundParameters[$_])
            }
         }
         
         try 
         {
            $exePath = "$env:SYSTEMROOT\system32\WindowsPowerShell\v1.0\PowerShell.exe"
            
            Write-Verbose "`$CommandLine: `"$exePath`" $($CommandLine -join ' ')"
            Write-Host "`r`nScript will now attempt to relaunch using elevation.`r`nPlease accept the request and follow progress in the new PowerShell window.`r`n"
            $process = Start-Process -FilePath $exePath -ErrorAction Stop -Verb Runas -ArgumentList $CommandLine -PassThru 
            Exit
         }
         catch 
         {
            Write-Warning "Elevation failed - $($_.Exception.Message)"
            Write-Warning "MDiag will continue without administrative privileges."
         }
      }
      else 
      {
         # Server 2003 ? (it is theoretically possible to install powershell there)
         Write-Verbose "Wow, really?! You got powershell running on a pre-6 kernel.. I salute you sir, good job old chap!"
         Write-Warning "System does not support UAC."
      }
   }
   
   Add-CompiledTypes
   
   Write-Verbose "`$SFSCTicketNumber: $SFSCTicketNumber"
   $script:DiagFile = Join-Path $([Environment]::GetFolderPath('Personal')) "mdiag-$($env:COMPUTERNAME).txt"

   Write-Verbose "`$DiagFile: $DiagFile"

   # get a SFSC ticket number if we don't already have one
   if (-not $script:SFSCTicketNumber)
   {
      $script:SFSCTicketNumber = Read-Host 'Please provide a MongoDB Technical Support case reference'
   }
}

#======================================================================================================================
function Add-CompiledTypes
#======================================================================================================================
{
   Add-Type @"
      using Microsoft.Win32;
      using System;
      using System.Text;
      using System.Runtime.InteropServices;

      public class MongoDB_Registry_Helper
      {         
         [DllImport("advapi32.dll", CharSet = CharSet.Auto)]
         public static extern int RegOpenKeyEx(
            IntPtr hKey,
            string subKey,
            int ulOptions,
            int samDesired,
            out UIntPtr hkResult);
   
         [DllImport("advapi32.dll", SetLastError=true, EntryPoint="RegQueryInfoKey")]
         public static extern int RegQueryInfoKey(
            UIntPtr hkey,
            out StringBuilder lpClass,
            ref uint lpcbClass,
            IntPtr lpReserved,
            IntPtr lpcSubKeys,
            IntPtr lpcbMaxSubKeyLen,
            IntPtr lpcbMaxClassLen,
            IntPtr lpcValues,
            IntPtr lpcbMaxValueNameLen,
            IntPtr lpcbMaxValueLen,
            IntPtr lpcbSecurityDescriptor,
            out long lpftLastWriteTime);
            
         const int KEY_QUERY_VALUE = 0x0001;
         
         public static long GetRegistryLastWrite(IntPtr lpRegistryHive, string key)
         {
            UIntPtr hkey = UIntPtr.Zero;
            
            if (RegOpenKeyEx(lpRegistryHive, key, 0, KEY_QUERY_VALUE, out hkey) != 0)
            {
               throw new Exception(string.Format("Unable to open {0}", key));
            }
            
            StringBuilder className = new StringBuilder();
            uint classLength = 0;
            long lastWriteTime;
            
            if (RegQueryInfoKey(hkey, out className, ref classLength, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 
                                    IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, out lastWriteTime) != 0)
            {
               throw new Exception("RegQueryInfoKey failed");
            }
            
            return lastWriteTime;
         }
      }      
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_FileCache_Utils
      {
         [DllImport("kernel32", SetLastError = true, CharSet = CharSet.Unicode)]
         public static extern bool GetSystemFileCacheSize(
            ref IntPtr lpMinimumFileCacheSize,
            ref IntPtr lpMaximumFileCacheSize,
            ref IntPtr lpFlags
            );

         public static bool GetFileCacheSize(ref IntPtr min, ref IntPtr max, ref IntPtr flags)
         {
            IntPtr lpMinimumFileCacheSize = IntPtr.Zero;
            IntPtr lpMaximumFileCacheSize = IntPtr.Zero;
            IntPtr lpFlags = IntPtr.Zero;

            bool result = GetSystemFileCacheSize(ref lpMinimumFileCacheSize, ref lpMaximumFileCacheSize, ref lpFlags);

            min = lpMinimumFileCacheSize;
            max = lpMaximumFileCacheSize;
            flags = lpFlags;
            
            return result;
         }
      }
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_CommandLine_Utils
      {
         [DllImport("shell32.dll", SetLastError = true)]
         static extern IntPtr CommandLineToArgvW(
            [MarshalAs(UnmanagedType.LPWStr)] string lpCmdLine, out int pNumArgs);

         public static string[] CommandLineToArgs(string commandLine)
         {
            if (String.IsNullOrEmpty(commandLine))
               return new string[] {};

            int argc;
            IntPtr argv = CommandLineToArgvW(commandLine, out argc);
            if (argv == IntPtr.Zero)
               throw new System.ComponentModel.Win32Exception();

            try
            {
               string[] args = new string[argc];
               for (int i = 0; i < args.Length; i++)
               {
                  IntPtr p = Marshal.ReadIntPtr(argv, i * IntPtr.Size);
                  args[i] = Marshal.PtrToStringUni(p);
               }

               return args;
            }
            finally
            {
               Marshal.FreeHGlobal(argv);
            }
          }
      }
"@

   Add-Type @"
      using System;
      using System.Runtime.InteropServices;

      public class MongoDB_Utils_ProcInfo
      {
         [DllImport("kernel32.dll", SetLastError=true)]
         public static extern bool GetLogicalProcessorInformation(
            IntPtr Buffer,
            ref uint ReturnLength
         );

         [StructLayout(LayoutKind.Sequential)]
         public struct CACHE_DESCRIPTOR
         {
            public byte Level;
            public byte Associativity;
            public ushort LineSize;
            public uint Size;
            public PROCESSOR_CACHE_TYPE Type;
         }

         public enum PROCESSOR_CACHE_TYPE
         {
            Unified = 0,
            Instruction = 1,
            Data = 2,
            Trace = 3,
         }
         
         [StructLayout(LayoutKind.Sequential)]
         public struct SYSTEM_LOGICAL_PROCESSOR_INFORMATION
         {
            public UIntPtr ProcessorMask;
            public LOGICAL_PROCESSOR_RELATIONSHIP Relationship;
            public ProcessorRelationUnion RelationUnion;
         }

         [StructLayout(LayoutKind.Explicit)]
         public struct ProcessorRelationUnion
         {
            [FieldOffset(0)] public CACHE_DESCRIPTOR Cache;
            [FieldOffset(0)] public uint NumaNodeNumber;
            [FieldOffset(0)] public byte ProcessorCoreFlags;
            [FieldOffset(0)] private UInt64 Reserved1;
            [FieldOffset(8)] private UInt64 Reserved2;
         }

         public enum LOGICAL_PROCESSOR_RELATIONSHIP : uint
         {
            RelationProcessorCore    = 0,
            RelationNumaNode         = 1,
            RelationCache            = 2,
            RelationProcessorPackage = 3,
            RelationGroup            = 4,
            RelationAll              = 0xffff
         }
         
         private const int ERROR_INSUFFICIENT_BUFFER = 122;
         
         public static SYSTEM_LOGICAL_PROCESSOR_INFORMATION[] GetLogicalProcessorInformation()
         {
            uint ReturnLength = 0;
            GetLogicalProcessorInformation(IntPtr.Zero, ref ReturnLength);
            if (Marshal.GetLastWin32Error() == ERROR_INSUFFICIENT_BUFFER)
            {
               IntPtr Ptr = Marshal.AllocHGlobal((int)ReturnLength);
               try
               {
                  if (GetLogicalProcessorInformation(Ptr, ref ReturnLength))
                  {
                     int size = Marshal.SizeOf(typeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
                     int len = (int)ReturnLength / size;
                     SYSTEM_LOGICAL_PROCESSOR_INFORMATION[] Buffer = new SYSTEM_LOGICAL_PROCESSOR_INFORMATION[len];
                     IntPtr Item = Ptr;
                     for (int i = 0; i < len; i++)
                     {
                        Buffer[i] = (SYSTEM_LOGICAL_PROCESSOR_INFORMATION)Marshal.PtrToStructure(Item, typeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
                        Item = (IntPtr)(Item.ToInt64() + (long)size);
                     }
                     return Buffer;
                  }
               }
               finally
               {
                  Marshal.FreeHGlobal(Ptr);
               }
            }
            return null;
         }
         
         public static uint GetNumberOfSetBits(uint value) 
         {
            uint num = 0;
            while (value > 0)
            {
               if ((value & 1) == 1)
                  num++;
               value >>= 1;
            }
            
            return num;
         }
      }
"@
}

#======================================================================================================================
function Get-RegistryLastWriteTime($RegistryKey)
#======================================================================================================================
{
   if (-not ($key = Get-Item $RegistryKey -ErrorAction SilentlyContinue))
   {
      return
   }
   
   $hive = $key.Name.Split('\',2)[0]
   $subkey = $key.Name.Split('\',2)[1]

   switch ($hive)
   {
      'HKEY_LOCAL_MACHINE'
      {
         $hivePtr = [Microsoft.Win32.RegistryHive]::LocalMachine.value__
      }
      
      default
      {
         throw "Unknown hive $hive"
      }
   }
   
   try
   {
      $timestamp = [MongoDB_Registry_Helper]::GetRegistryLastWrite($hivePtr, $subkey)
      return [DateTime]::FromFileTime($timestamp)
   }
   catch
   {
      throw $_.Exception.Message
   } 
}

#======================================================================================================================
function Collect-PerformanceCounters($Samples = 60, $IntervalSeconds = 1)
#======================================================================================================================
{
   $counterList = Get-Counter -ListSet *   
   $counters = @()
   
   ## Paging File counters
   $counters += $counterList | ? { $_.CounterSetName -eq 'Paging File' } | Select -ExpandProperty PathsWithInstances | ? { $_ -match '^\\Paging File\([^_][^)]*\)\\% Usage$' }
   
   ## Memory counters
   $counters += @('\Memory\Available Bytes',
                  '\Memory\Committed Bytes',
                  '\Memory\Commit Limit',
                  '\Memory\Modified Page List Bytes',
                  '\Memory\Page Faults/sec',
                  '\Memory\Page Reads/sec',
                  '\Memory\Page Writes/sec',
                  '\Memory\Pages Input/sec',
                  '\Memory\Pages Output/sec',
                  '\Memory\Cache Faults/sec',
                  '\Memory\Cache Bytes',
                  '\Memory\Cache Bytes Peak',
                  '\Memory\Transition Faults/sec'
               )
   
   ## CPU time counters
   $counters += @('\Processor(_total)\% Processor Time',
                  '\Processor(_total)\% User Time',
                  '\Processor(_total)\% Privileged Time',
                  '\Processor(_total)\% Interrupt Time',
                  '\Processor(_total)\% DPC Time',
                  '\Processor(_total)\% Idle Time'
               )

   ## IO counters
   $counters += $counterList | ? { $_.CounterSetName -eq 'PhysicalDisk' } | Select -ExpandProperty PathsWithInstances | ? { $_ -match '^\\PhysicalDisk\([^_][^)]*\)\\' }
   
   Write-Verbose "Collecting the following counters:`r`n - $($counters -join `"`r`n - `")"
   
   $timeSpanComplete = New-TimeSpan -Seconds ($Samples * $IntervalSeconds)
   
   Write-Host "Collecting $($counters.Length) performance counters over a period of $($timeSpanComplete.TotalSeconds) seconds"
   Write-Host "This will complete at $((Get-Date).Add($timeSpanComplete).ToString())"
   
   $counterData = [Microsoft.PowerShell.Commands.GetCounter.PerformanceCounterSampleSet[]] (Get-Counter $counters -MaxSamples $Samples -SampleInterval $IntervalSeconds)
   
   if (Get-Command Export-Counter -ErrorAction SilentlyContinue)
   {
      ## Export PerfMon counters to both binary and csv format
      #  - timeseries.py is able to interpret .csv format
      #  - perfmon.exe is able to interpret .blg format and uses metadata such as counter scale

      try
      {
         $binaryPerformanceLog = [IO.Path]::Combine([IO.Path]::GetTempPath(), "PerfMonCounters-$($env:COMPUTERNAME).blg")
         Write-Verbose "Exporting Performance Counters to $binaryPerformanceLog"
         [Microsoft.PowerShell.Commands.GetCounter.PerformanceCounterSampleSet[]] $counterData | Export-Counter -Force -FileFormat BLG $binaryPerformanceLog -ErrorAction Stop
         $script:FilesToCompress += $binaryPerformanceLog
      }
      catch
      {
         Write-Verbose "Unable to export Performance Counters to $binaryPerformanceLog - $($_.Exception.Message)"
      }

      try
      {
         $csvPerformanceLog = [IO.Path]::Combine([IO.Path]::GetTempPath(), "PerfMonCounters-$($env:COMPUTERNAME).csv")
         Write-Verbose "Exporting Performance Counters to $csvPerformanceLog"
         [Microsoft.PowerShell.Commands.GetCounter.PerformanceCounterSampleSet[]] $counterData | Export-Counter -Force -FileFormat CSV $csvPerformanceLog -ErrorAction Stop
         $script:FilesToCompress += $csvPerformanceLog
      }
      catch
      {
         Write-Verbose "Unable to export Performance Counters to $csvPerformanceLog - $($_.Exception.Message)"
      }
   }
   
   ## If we were unable to export counters fallback to embedding counter data as json documents within results
   if (-not $csvPerformanceLog -or $script:FilesToCompress -notcontains $csvPerformanceLog)
   {
      $counterData | % { 
         $results = New-Object Collections.Specialized.OrderedDictionary
         $_ | Select -ExpandProperty CounterSamples | Sort-Object Path | % { $results.Add($_.Path.Split('\',4)[3], $_.CookedValue) } 
      
         @{ Timestamp = $_.Timestamp; Counters = $results }
      }
   }
}

#======================================================================================================================
# Wrapper to extract entries from Windows event log
#======================================================================================================================
function Extract-EventLogEntries($FilterXml, $Limit = 10)
#======================================================================================================================
{
   ## Get-WinEvent on PowerShell 2.0 doesn't return a message when culture is not en-US
   
   if ($PSVersionTable.PSVersion -eq '2.0' -and (Get-Culture).Name -ne 'en-US')
   {
      $origCulture = Get-Culture

      try
      {
         [Threading.Thread]::CurrentThread.CurrentCulture = New-Object System.Globalization.CultureInfo 'en-US'
         $events = Get-WinEvent -FilterXml $FilterXml -MaxEvents $Limit -ErrorAction Stop
      }
      catch
      {
         throw $_.Exception.Message
      }
      finally
      {
         [System.Threading.Thread]::CurrentThread.CurrentCulture = $origCulture
      }
   }
   else
   {
      ## This will throw an exception if no events are found
      $events = Get-WinEvent -FilterXml $FilterXml -MaxEvents $Limit -ErrorAction Stop
   }
   
   if (-not $events)
   {
      return
   }
   
   $events | Sort-Object -Descending TimeCreated | `
      Select TimeCreated, ProviderName, Id, LevelDisplayName, Message, ProcessId, ThreadId, @{ Name = 'UserId'; Expression = { $_.UserId.Value } }
}

#======================================================================================================================
# Script portion
#======================================================================================================================
#
#   This is where you define the tests you want to run, using the document structure definition provided:
#
#   probe @{ name = "", cmd = "", alt = "" }
#   
#   name = verbatim content of the "section" value in the output for this probe result
#   cmd = powershell command-line to execute and capture output from
#   alt = alternative to cmd to try if 'cmd' reports any kind of error (stderr still goes to the console)
#
#======================================================================================================================
function Get-Probes
#======================================================================================================================
{   
   # @todo: check to see if mongod is open to the internet

   @{ name = "computersystem";
      cmd = "Get-WmiClassProperties Win32_ComputerSystem"
   }
   
   @{ name = "operatingsystem";
      cmd = "Get-WmiClassProperties Win32_OperatingSystem"
   }
   
   @{ name = "quickfixengineering";
      cmd = "Get-WmiClassProperties Win32_QuickFixEngineering"
   }
   
   @{ name = "reliabilityrecords";
      cmd = "Get-WmiClassProperties Win32_ReliabilityRecords"
   }
   
   @{ name = "is_admin";
      cmd = "([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"
   }

   @{ name = "memory-virtual";
      cmd = "Get-WmiClassProperties Win32_PerfRawData_PerfOS_Memory"
   }

   @{ name = "vm-hyperv-dynamicmemory";
      cmd = @"
         # Get-Counter '\Hyper-V Dynamic Memory Integration Service\*'
         try
         {
            Get-Counter '\Hyper-V Dynamic Memory Integration Service\*' -ErrorAction Stop | Select -ExpandProperty CounterSamples | % { @{ `$_.Path.Split('\',4)[3] = `$_.CookedValue } }
         }
         catch
         {
            throw "Unable to load 'Hyper-V Dynamic Memory Integration Service' counters"
         }
"@
   }
   
   @{ name = "vm-vmware-memory";
      cmd = @"
         # Get-Counter '\VM Memory\*'
         try
         {
            Get-Counter '\VM Memory\*' -ErrorAction Stop | Select -ExpandProperty CounterSamples | % { @{ `$_.Path.Split('\',4)[3] = `$_.CookedValue } }
         }
         catch
         {
            throw "Unable to load 'VM Memory' counters"
         }
"@
   }

   @{ name = "vm-vmware-processor";
      cmd = @"
         # Get-Counter '\VM Processor\*'
         try
         {
            Get-Counter '\VM Processor\*' -ErrorAction Stop | Select -ExpandProperty CounterSamples | % { @{ `$_.Path.Split('\',4)[3] = `$_.CookedValue } }
         }
         catch
         {
            throw "Unable to load 'VM Processor' counters"
         }
"@
   }
   
   @{ name = "memory-physical";
      cmd = "Get-WmiObject Win32_PhysicalMemory | Select BankLabel,DeviceLocator,FormFactor,Capacity,Speed"
   }

   @{ name = "memory-pagefilesetting";
      cmd = "Get-WmiClassProperties Win32_PageFileSetting"
   }

   @{ name = "memory-pagefileusage";
      cmd = "Get-WmiClassProperties Win32_PageFileUsage"
   }
   
   @{ name = "bios";
      cmd = "Get-WmiClassProperties Win32_Bios"
   }
   
   @{ name = "kernel-boot";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-General' and 'Microsoft-Windows-Kernel-Boot'
         
         if (-not (Get-WinEvent -ListProvider 'Microsoft-Windows-Kernel-Boot' -ErrorAction SilentlyContinue))
         {
            $filterXml = @"
               <QueryList>
                  <Query Id="0" Path="System">
                     <Select Path="System">*[System[Provider[@Name='EventLog'] and (EventID != 6013 and EventID != 6005)]]</Select>
                  </Query>
               </QueryList>
"@
         }
         else
         {
            $filterXml = @"
               <QueryList>
                  <Query Id="0" Path="System">
                     <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=12 or EventID=13)]]</Select>
                  </Query>
                  <Query Id="1" Path="System">
                     <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Boot']]]</Select>
                  </Query>
               </QueryList>
"@
         }
         
         Extract-EventLogEntries $filterXml 20
'@
   }
   
   @{ name = "tcpip-eventlog";
      cmd = @'
         # Extract-EventLogEntries for 'Tcpip'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Tcpip'] and (Level=1 or Level=2 or Level=3)]]</Select>
               </Query>
            </QueryList>
"@         
         Extract-EventLogEntries $filterXml 20
'@
   }
   
   @{ name = "kernel-disk";
      cmd = @'
         # Extract-EventLogEntries for 'disk' and 'Microsoft-Windows-Disk'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='disk']]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Disk']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 20
'@
   }
   
   @{ name = "kernel-power";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-Power' and 'Microsoft-Windows-Kernel-Processor-Power'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Power']]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-Processor-Power']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 50
'@
   }
   
   @{ name = "kernel-filtermanager";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-FilterManager'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-FilterManager']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 30
'@
   }
   
   @{ name = "hardware-cpu";
      cmd = 'Get-WmiClassProperties Win32_Processor'
   }
   
   @{ name = "tasklist";
      cmd = @'
         $processes = Get-WmiObject Win32_Process
         Get-Process | % `
         {
            $processId = $_.Id
            $proc = $processes | ? { $_.ProcessId -eq $processId }
            
            Select -InputObject $_ -Property @{ Name = 'Name'; Expr = { if ($_.MainModule.ModuleName) { $_.MainModule.ModuleName } else { $proc.ProcessName } } }, Id, 
               @{ Name = 'ParentProcessId'; Expr = { $proc.ParentProcessId } },
               Path, Description, Company, Product, FileVersion, ProductVersion, 
               BasePriority, PriorityClass, PriorityBoostEnabled, HandleCount, MinWorkingSet, MaxWorkingSet, 
               @{ Name = 'Modules'; Expr = { $_.Modules.FileName } }, 
               NonpagedSystemMemorySize64, PagedMemorySize64, PeakPagedMemorySize64, PagedSystemMemorySize64, VirtualMemorySize64, PeakVirtualMemorySize64, WorkingSet64, PeakWorkingSet64, PrivateMemorySize64, 
               @{ Name = 'StartTime'; Expr = { [DateTime] $_.StartTime } },
               UserProcessorTime, PrivilegedProcessorTime, TotalProcessorTime,
               @{ Name = 'ThreadCount'; Expr = { $_.Threads.Count } },
               @{ Name = 'Threads'; Expr = { $_.Threads.Id } },
               @{ Name = 'CommandLine'; Expr = { $proc.CommandLine } },
               @{ Name = 'ReadOperationCount'; Expr = { $proc.ReadOperationCount } },
               @{ Name = 'ReadTransferCount'; Expr = { $proc.ReadTransferCount } },
               @{ Name = 'WriteOperationCount'; Expr = { $proc.WriteOperationCount } },
               @{ Name = 'WriteTransferCount'; Expr = { $proc.WriteTransferCount } },
               @{ Name = 'OtherOperationCount'; Expr = { $proc.OtherOperationCount } },
               @{ Name = 'OtherTransferCount'; Expr = { $proc.OtherTransferCount } }
         }
'@
   }
   
   @{ name = "mongod-configuration";
      cmd = @'      
         Get-WmiObject Win32_Process -Filter "Name LIKE 'mongod%'" | % {
            if (-not $_.CommandLine)
            {
               throw "Unable to determine command line for $($_.Name) ($($_.ProcessId))"
            }
            
            $array = @()
            
            [MongoDB_CommandLine_Utils]::CommandLineToArgs($_.CommandLine) | % { 
               if (-not $_.Contains('='))
               {
                  $array += $_
                  return
               }
               $_.Split('=',2) | % { $array += $_ }
            }
            
            $path = $null
            
            for ($i = 0; $i -lt $array.Length; $i++)
            {
               if ('-f','--config' -contains $array[$i] -and $i+1 -le $array.Length-1)
               {
                  $path = $array[$i+1]
               }
               
               if ($path -and -not ([IO.Path]::IsPathRooted($path)))
               {
                  $path = [IO.Path]::Combine(([IO.Path]::GetDirectoryName($_.ExecutablePath)), ([IO.Path]::GetFileName($path)))
               }
            }
            
            if (-not $path)
            {
               return
            }

            Write-Verbose "Discovered configuration file $path"
            
            @{ ConfigurationFilePath = $path;
               ProcessId = $_.ProcessId
               ExecutablePath = $_.ExecutablePath;
               ConfigFile = (Redact-ConfigFile $path)
            }
         }
'@
   }
   
   @{ name = "mongod-dir-listing";
      cmd = @'      
         Get-WmiObject Win32_Process -Filter "Name LIKE 'mongod%'" | % {
         
            if (-not $_.CommandLine)
            {
               throw "Unable to determine command line for $($_.Name) ($($_.ProcessId))"
            }
            
            $array = @()
            
            [MongoDB_CommandLine_Utils]::CommandLineToArgs($_.CommandLine) | % { 
               if (-not $_.Contains('='))
               {
                  $array += $_
                  return
               }
               $_.Split('=',2) | % { $array += $_ }
            }
            
            $dbPath = $null
            $path = $null
            
            for ($i = 0; $i -lt $array.Length; $i++)
            {
               if ('--dbpath' -contains $array[$i] -and $i+1 -le $array.Length-1)
               {
                  $dbPath = $array[$i+1]
               }
               
               if (-not $dbPath)
               {
                  if ('-f','--config' -contains $array[$i] -and $i+1 -le $array.Length-1)
                  {
                     $path = $array[$i+1]
                  }
                  
                  if ($path)
                  {
                     $dbPath = [IO.File]::ReadAllText($path) | ? { $_ -match 'storage:[\W]+dbPath:[\W]+([^\n\r]+)' }  | % { $Matches[1] }
                  }
               }
               
               if ($dbPath -and -not ([IO.Path]::IsPathRooted($dbPath)))
               {
                  $dbPath = [IO.Path]::Combine(([IO.Path]::GetDirectoryName($_.ExecutablePath)), ([IO.Path]::GetFileName($dbPath)))
               }
            }
            
            if (-not $dbPath)
            {
               return
            }

            Write-Verbose "Discovered dbPath $dbPath"
            
            $dirListing = Get-ChildItem -Recurse $dbPath | Select FullName, Length, Mode, `
                                                                  @{ Name = 'CreationTime'; Expression = { _iso8601_string $_.CreationTime } }, `
                                                                  @{ Name = 'LastWriteTime'; Expression = { _iso8601_string $_.LastWriteTime } } | Format-Table | Out-String

            @{ DbFilePath = $dbPath;
               ProcessId = $_.ProcessId
               ExecutablePath = $_.ExecutablePath;
               DirectoryListing = $dirListing.Split("`n").TrimEnd()
            }
         }
'@
   }
   
   @{ name = "network-adapter";
      cmd = "Get-NetAdapter | Select ifIndex,ifAlias,ifDesc,ifName,DriverVersion,MacAddress,Status,LinkSpeed,MediaType,MediaConnectionState,DriverInformation,DriverFileName,NdisVersion,DeviceName,DriverName,DriverVersionString,MtuSize";
      alt = "netsh wlan show interfaces";
   }
   
   @{ name = "network-interface";
      cmd = "Get-NetIPAddress | Select ifIndex,PrefixOrigin,SuffixOrigin,Type,AddressFamily,AddressState,Name,ProtocolIFType,IPv4Address,IPv6Address,IPVersionSupport,PrefixLength,SubnetMask,InterfaceAlias,PreferredLifetime,SkipAsSource,ValidLifetime";
      alt = "ipconfig /all";
   }
   
   @{ name = "network-route";
      cmd = "Get-NetRoute | Select DestinationPrefix,InterfaceAlias,InterfaceIndex,RouteMetric,TypeOfRoute";
      alt = "route print";
   }
   
   @{ name = "spn-registrations";
      cmd = @'
         # Get SPN registrations

         try
         {
            $sysInfo = New-Object -ComObject "ADSystemInfo"
            $machineDN = $sysInfo.GetType().InvokeMember("ComputerName", [Reflection.BindingFlags]::GetProperty, $null, $sysInfo, $null)
            ([ADSI] "LDAP://$machineDN").servicePrincipalName
         }
         catch 
         {
            $ex = $_.Exception
            if ($ex.InnerException -and $ex.InnerException.Message)
            {
               throw $ex.InnerException.Message
            }
            
            throw $ex.Message
         }
'@
   }
   
   @{ name = "network-dns-cache";
      cmd = "Get-DnsClientCache | Get-Unique | Select Entry,Name,Data,DataLength,Section,Status,TimeToLive,Type";
   }
   
   @{ name = "network-tcp-active";
      cmd = "netstat -ano -p TCP | select -skip 3 | foreach {`$_.Substring(2) -replace `" {2,}`",`",`" } | ConvertFrom-Csv"
   }

   @{ name = "services";
      cmd = "Get-WmiObject Win32_Service | Select Name, Status, ExitCode, DesktopInteract, ErrorControl, PathName, ServiceType, ServiceSpecificExitCode, StartName, Caption, Description, DisplayName, StartMode, ProcessId, Started, State";
      altcmd = "Get-Service | Select Di*,ServiceName,ServiceType,@{Name='Status';Expression={`$_.Status.ToString()}},@{Name='ServicesDependedOn';Expression={@(`$_.ServicesDependedOn.Name)}}";
   }

   @{ name = "firewall";
      cmd = "Get-NetFirewallRule | Where-Object {`$_.DisplayName -like '*mongo*'} | Select Name,DisplayName,Enabled,@{Name='Profile';Expression={`$_.Profile.ToString()}},@{Name='Direction';Expression={`$_.Direction.ToString()}},@{Name='Action';Expression={`$_.Action.ToString()}},@{Name='PolicyStoreSourceType';Expression={`$_.PolicyStoreSourceType.ToString()}}";
   }

   @{ name = "storage-fsutil";
      cmd = "fsutil behavior query DisableLastAccess; fsutil behavior query EncryptPagingFile"
   }
   
   @{ name = "storage-disk";
      cmd = "Get-Disk | Select PartitionStyle,ProvisioningType,OperationalStatus,HealthStatus,BusType,BootFromDisk,FirmwareVersion,FriendlyName,IsBoot,IsClustered,IsOffline,IsReadOnly,IsSystem,LogicalSectorSize,Manufacturer,Model,Number,NumberOfPartitions,Path,PhysicalSectorSize,SerialNumber,Size";
      alt = "Get-WmiObject Win32_DiskDrive | Select SystemName,BytesPerSector,Caption,CompressionMethod,Description,DeviceID,InterfaceType,Manufacturer,MediaType,Model,Name,Partitions,PNPDeviceID,SCSIBus,SCSILogicalUnit,SCSIPort,SCSITargetId,SectorsPerTrack,SerialNumber,Signature,Size,Status,TotalCylinders,TotalHeads,TotalSectors,TotalTracks,TracksPerCylinder";
   }
   
   @{ name = "storage-partition";
      # DriverLetter is borked, need to detect the nul byte included in the length for non-mapped partitions (..yeah)
      cmd = "Get-Partition | Select OperationalStatus,Type,AccessPaths,DiskId,DiskNumber,@{Name='DriveLetter';Expression={@(`$null,`$_.DriveLetter)[`$_.DriveLetter[0] -ge 'A']}},GptType,Guid,IsActive,IsBoot,IsHidden,IsOffline,IsReadOnly,IsShadowCopy,IsSystem,MbrType,NoDefaultDriveLetter,Offset,PartitionNumber,Size,TransitionState";
      alt = "Get-WmiClassProperties Win32_DiskPartition"
   }
   
   @{ name = "storage-volume";
      cmd = 'Get-Volume | Select OperationalStatus, HealthStatus, DriveType, FileSystemType, DedupMode, Path, AllocationUnitSize, @{ Name = "DriveLetter"; Expression = {@($null,$_.DriveLetter)[$_.DriveLetter[0] -ge "A"]}}, FileSystem, FileSystemLabel, Size, SizeRemaining';
      alt = "Get-WmiObject Win32_LogicalDisk | Select Compressed,Description,DeviceID,DriveType,FileSystem,FreeSpace,MediaType,Name,Size,SystemName,VolumeSerialNumber";
   }

   @{ name = "environment";
      cmd = "Get-Childitem env: | ForEach-Object {`$j=@{}} {`$j.Add(`$_.Name,`$_.Value)} {`$j}";
   }

   #@{ name = "user-list-local";
   #  cmd = "Get-WMIObject Win32_UserAccount | Where-Object {`$_.LocalAccount -eq `$true} | Select Caption,Name,Domain,Description,AccountType,Disabled,Lockout,SID,Status";
   #}

   @{ name = "drivers";
      cmd = "Get-WmiObject Win32_SystemDriver | Select Name, Description, PathName, ServiceType, StartMode, Status"
   }

   @{ name = "time-change";
      cmd = @'
         # Extract-EventLogEntries for 'Microsoft-Windows-Kernel-General' and 'Microsoft-Windows-Time-Service'
         
         $filterXml = @"
            <QueryList>
               <Query Id="0" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Kernel-General'] and (EventID=1)]]</Select>
               </Query>
               <Query Id="1" Path="System">
                  <Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Time-Service']]]</Select>
               </Query>
            </QueryList>
"@
         
         Extract-EventLogEntries $filterXml 20
'@
   }

   @{ name = "kerberos-parameters";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Control\Lsa\Kerberos\Parameters'
   }
   
   @{ name = "tcpip-parameters";
      cmd = 'Get-RegistryValues HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters'
   }
   
   @{ name = "storage-filecachesize";
      cmd = @'
         # Interop call to GetSystemFileCacheSize()

         $min = $max = $flags = 0

         if ([MongoDB_FileCache_Utils]::GetFileCacheSize([ref] $min, [ref] $max, [ref] $flags))
         {
            @{ min = $min; max = $max; flags = $flags }
         }
'@ }

   @{ name = "hardware-logicalprocessors";
      cmd = @'
         # Interop call to GetLogicalProcessorInformation()

         $procCaches = @()

         [MongoDB_Utils_ProcInfo]::GetLogicalProcessorInformation() | % {
            
            $obj = $_
            
            switch ($obj.Relationship) 
            {
               'RelationNumaNode'
               {
                  # Non-NUMA systems report a single record of this type.
                  $numaNodeCount += 1
                  break
               }
               
               'RelationProcessorCore'
               {
                  $processorCoreCount += 1

                  # A hyperthreaded core supplies more than one logical processor.
                  $num = [MongoDB_Utils_ProcInfo]::GetNumberOfSetBits($obj.ProcessorMask)
                  
                  # Write-Host "$($obj.ProcessorMask) = $num"
                  $logicalProcessorCount += $num
                  break
               }
               
               'RelationCache'
               {
                  $procCaches += ($cache = $obj | Select -ExpandProperty RelationUnion | Select -ExpandProperty Cache | `
                                    Select @{ Name = 'ProcessorMask'; Expression = { $obj.ProcessorMask } }, Level, Type, LineSize, Size)
                  break
               }
               
               'RelationProcessorPackage'
               {
                  # Logical processors share a physical package.
                  $processorPackageCount += 1
                  break
               }
               
               default
               {
                  Write-Warning "Unsupported LOGICAL_PROCESSOR_RELATIONSHIP value: $($obj.Relationship)"
                  break
               }
            }
         }

         $results = @{}
         $results.Add("NUMA nodes", $numaNodeCount)
         $results.Add("Physical processor packages", $processorPackageCount)
         $results.Add("Processor cores", $processorCoreCount)
         $results.Add("Logical processors", $logicalProcessorCount)
         $results.Add("Processor caches", $procCaches)
         $results
'@ }

   # @todo: capture other vendor exception lists

   @{ name = 'mcafee-onaccess-exclusions';
      cmd = 'Get-RegistryValues "HKLM:\Software\Wow6432Node\McAfee\SystemCore\vscore\On Access Scanner\McShield\Configuration\Default"'
   }

   @{ name = 'windows-defender';
      cmd = @'
         # Windows Defender Real-Time Protection and Exclusion settings
         Get-RegistryValues "HKLM:\Software\Microsoft\Windows Defender\Real-Time Protection"
         Get-RegistryValues "HKLM:\Software\Microsoft\Windows Defender\Exclusions"
'@
   }
   
   @{ name = 'windows-eventlogs';
      cmd = @'
         Get-WmiObject Win32_NTEventlogFile | ? { 'Application','System' -contains $_.LogfileName } | % { `
            $destFile = [IO.Path]::Combine([IO.Path]::GetTempPath(), "$($env:COMPUTERNAME)_$([IO.Path]::GetFileName($_.Name))")

            Write-Verbose "Exporting $($_.LogfileName) to $destFile"
            $_.BackupEventlog($destFile) | Out-Null

            $script:FilesToCompress += $destFile
            
            $_ | Select LogFileName, Name, NumberOfRecords, FileSize, MaxFileSize, OverwriteOutDated, OverwritePolicy
         }
'@
   }
}

#======================================================================================================================
# Call script entrypoint
#======================================================================================================================
Main