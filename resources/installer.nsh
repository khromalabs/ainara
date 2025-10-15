!macro customInstall
  ; Add firewall rule for the Orakle server
  AdvFirewall::AddRule /NOUNLOAD \
    Name="Ainara Polaris Orakle Server (Port 8100)" \
    FileName="$INSTDIR\bin\servers\orakle.exe" \
    Action=Allow \
    Direction=In \
    Protocol=TCP \
    LocalPorts=8100

  ; Add firewall rule for the Pybridge server
  AdvFirewall::AddRule /NOUNLOAD \
    Name="Ainara Polaris Pybridge Server (Port 8101)" \
    FileName="$INSTDIR\bin\servers\pybridge.exe" \
    Action=Allow \
    Direction=In \
    Protocol=TCP \
    LocalPorts=8101
!macroend
