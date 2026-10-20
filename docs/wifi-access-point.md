# Optional Wi-Fi access point for Web Admin

PunchClock can be administered over a dedicated local Wi-Fi network when the Raspberry Pi has a Wi-Fi adapter that supports access-point (AP) mode. This is **optional**: PunchClock does not create or configure an access point automatically, and the standard installation does not install the required AP software.

## Validated approach

A reference terminal was manually configured and tested with the following components:

- **hostapd** creates the WPA2-protected Wi-Fi access point on `wlan0`.
- **dnsmasq** provides DHCP addresses to Wi-Fi clients (DNS service is not required for DHCP).
- **NetworkManager** continues managing the wired `eth0` connection but does not manage `wlan0`.
- A **systemd oneshot service** assigns the static address `10.77.0.1/24` to `wlan0` at boot, before hostapd and dnsmasq.
- **Avahi/mDNS** allows compatible clients to resolve the terminal's `.local` hostname.

On the tested terminal, the SSID was `PunchClock-Menjador`, the access point used 2.4 GHz channel 6 with regulatory country `ES`, and the Web Admin was accessible at:

- `http://192.168.50.1:8000/admin`
- `http://punchmenjador.local:8000/admin` (on clients supporting mDNS)

Access was verified from a phone and a PC connected to the Wi-Fi, including after reboot. The Wi-Fi was deliberately isolated from Internet routing and Ethernet forwarding; clients may report that the network has no Internet access. The terminal's clocking functionality remains independent of network availability.

## Manual configuration required

This is **documentation of a tested capability, not an automated installation procedure**. An administrator must manually install and configure the additional packages (notably `hostapd` and `dnsmasq`), set the SSID and a unique strong WPA2 passphrase, configure the Wi-Fi regulatory country and channel, assign a static IP, restrict DHCP to the Wi-Fi interface, and configure systemd startup ordering. The Wi-Fi adapter and driver must support AP mode; support is hardware-dependent.

The tested setup required configuring NetworkManager to leave only `wlan0` unmanaged, while retaining its management of `eth0`. Do **not** disable NetworkManager globally on a remotely managed terminal. A NetworkManager-managed AP was attempted on the reference Broadcom adapter but failed to initialize; a manual hostapd setup successfully started the AP. This does not mean NetworkManager AP mode is unsupported on all hardware.

The example subnet, SSID, hostname and country are installation-specific and should not be assumed for other sites. Avoid IP conflicts with the wired network. Store the Wi-Fi passphrase only in a root-readable local configuration file; never commit it to Git. Verify that IP forwarding remains disabled and that Wi-Fi clients cannot reach the wired network through the terminal.

## Security and verification

Web Admin currently uses **plain HTTP**, so passwords and sessions are not protected against interception by other devices on the Wi-Fi. Use a strong, private WPA2 password, share it only with authorized administrators, and do not treat this access point as a public or guest network. For stronger protection, deploy HTTPS before using an untrusted network.

After manual setup, verify that `hostapd` and `dnsmasq` are active, `wlan0` has the intended static address, `eth0` remains connected, a client receives a DHCP lease, and Web Admin works by IP. Test hostname resolution separately because `.local` support varies by client. Repeat these checks after a full reboot.

The current PunchClock installer (`deploy/install.sh`) **does not install or configure this Wi-Fi AP**. No AP setup script or configuration templates are distributed at present.
