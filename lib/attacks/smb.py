# fix debug output, not seeing enough info "or any info"

from lib.ldap import init_ldap_session
from lib.logger import logger, printlog
from lib.attacks.find import SCCMHUNTER
from impacket.smbconnection import SMBConnection
import ntpath
import os
import csv
import pandas as pd
from tabulate import tabulate
from lib.scripts.banner import show_banner



class SMB:
    
    def __init__(self, username=None, password=None, domain=None, target_dom=None, 
                    dc_ip=None,ldaps=False, kerberos=False, no_pass=False, hashes=None, 
                    aes=None, debug=False, save=False,
                    logs_dir=None):
        self.username = username
        self.password = password
        self.domain = domain
        self.target_dom = target_dom
        self.dc_ip = dc_ip
        self.ldaps = ldaps
        self.kerberos = kerberos
        self.no_pass = no_pass
        self.hashes=hashes
        self.aes = aes
        self.save = save
        self.logs_dir = logs_dir
        self.debug = debug
        self.ldap_session = None
        self.search_base = None
        self.test_array = []


 
    def run(self):
        logfile = f"{self.logs_dir}/sccmhunter.log"
        if os.path.exists(logfile):
            logger.info("[+] Found targets from logfile.")
            targets = self.read_logs()
            self.smb_hunter(targets)
        else:
            logger.info("[-] Existing log file not found, searching LDAP for site servers.")
            sccmhunter = SCCMHUNTER(username=self.username, password=self.password, domain=self.domain, 
                                    target_dom=self.target_dom, dc_ip=self.dc_ip,ldaps=self.ldaps,
                                    kerberos=self.kerberos, no_pass=self.no_pass, hashes=self.hashes, 
                                    aes=self.aes, debug=self.debug, logs_dir=self.logs_dir)
            sccmhunter.run()
            self.run()

    def read_logs(self):
        targets = []
        with open(f"{self.logs_dir}/sccmhunter.log", "r") as f:
            for line in f.readlines():
                targets.append(line.strip())
        return targets

    def smb_hunter(self, servers):
        pxe_boot_servers = []
        for i in servers:
            try:
                timeout = 10
                server = str(i)
                # might need some DNS resolution here for site servers
                conn = SMBConnection(server, server, None, timeout=timeout)
                # need to setup kerberos authentication here too...
                conn.login(user=self.username, password=self.password, domain=self.domain)
                logger.debug(f"[+] Connected to smb://{server}:445")

                signing = conn.isSigningRequired()
                site_code = ''
                siteserv = False
                dp = False

                if not signing:
                    logger.debug(f"[+] SMB signing not required on {server}")
                else:
                    logger.debug(f"[-] SMB signing requred on {server}")

                for share in conn.listShares():
                    remark = share['shi1_remark'][:-1]
                    name = share['shi1_netname'][:-1]
                    #default remarks reveal role
                    if name == "SMS_DP$" and "SMS Site" in remark:
                        siteserv=False
                        dp = True
                        site_code = (remark.split(" ")[-3])
                    if name == "SMS_SITE":
                        siteserv = True
                        dp = True
                        site_code = (remark.split(" ")[-2])
                    if name =="REMINST":
                        check = conn.listPath(shareName="REMINST", path="SMSTemp//*")
                        if "STATUS_OBJECT_NAME_NOT_FOUND" not in check:
                            pxe_boot_servers.append(server)

                self.test_array.append({'Hostname': f'{server}', 
                                        'Signing Status': f'{signing}', 
                                        'Site Code': f'{site_code}',
                                        'Site Server' : f'{siteserv}', 
                                        'Distribution Point': f'{dp}'})
            except Exception as e:
                logger.info(f"[-] {e}")
        
        # spider and save the paths of variables files if discovered with optional save
        if pxe_boot_servers:
            self.smb_spider(conn, pxe_boot_servers)
        # both of these can be imported from a library since it's being used similarly for other modules
        if self.test_array:
            self.save_csv(self.test_array)
            self.print_table()

    def smb_spider(self, conn, targets):
        vars_files = []
        downloaded = []
        for target in targets:
            try:
                logger.info(f'[*] Searching {target} for PXEBoot variables files.')
                for shared_file in conn.listPath(shareName="REMINST", path="SMSTemp//*"):
                    if shared_file.get_longname().endswith('.var'):
                        # store full path for easy reporting
                        full_path = (f"\\\\{target}\\REMINST\\SMSTemp\\{shared_file.get_longname()}")
                        vars_files.append(full_path)
                        logger.debug(f"[+] Found {full_path}")
                        if self.save:
                            file_name = shared_file.get_longname()
                            fh = open(ntpath.basename(file_name), 'wb')
                            path = f"SMSTemp//{file_name}"
                            try:
                                conn.getFile(shareName="REMINST",pathName = path, callback=fh.write)
                                downloaded.append(file_name)
                            except Exception as e:
                                print(e)
                                print("shit broke")
            except Exception as e:
                print(e)
        conn.logoff()
        
        if len(downloaded) > 0:
            logger.info("[+] Variables files downloaded!")
            for i in (downloaded):
                os.replace(f'{os.getcwd()}/{i}', f'{self.logs_dir}/loot/{i}')
        if vars_files:
            filename = "smbhunter.log"
            printlog(vars_files, self.logs_dir, filename)

        
    def save_csv(self, array):
        fields = ["Hostname", "Signing Status", "Site Code","Site Server", "Distribution Point"]
        with open(f'{self.logs_dir}/csvs/smbhunter.csv', 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(array)
        f.close()
        
    
    def print_table(self):
        df = pd.read_csv(f"{self.logs_dir}/csvs/smbhunter.csv")
        logger.info(tabulate(df, headers = 'keys', tablefmt = 'grid'))
        logger.info(f'SMB results saved to {self.logs_dir}/smbhunter.csv')


    def printlog(self, servers):
        filename = (f'{self.logs_dir}/smbhunter.log')
        logger.info(f'[+] Results saved to {filename}')
        for server in servers:
            with open(filename, 'a') as f:
                f.write("{}\n".format(server))
                f.close

