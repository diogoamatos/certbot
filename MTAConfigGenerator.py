#!/usr/bin/env python

import sys
import string
import os, os.path

def parse_line(line_data):
    """
    Return the (line number, left hand side, right hand side) of a stripped
    postfix config line.

    Lines are like:
    smtpd_tls_session_cache_database = btree:${data_directory}/smtpd_scache
    """
    num,line = line_data
    left, sep, right = line.partition("=")
    if not sep:
        return None
    return (num, left.strip(), right.strip())

class MTAConfigGenerator:
    def __init__(self, policy_config):
        self.policy_config = policy_config

class ExistingConfigError(ValueError): pass

class PostfixConfigGenerator(MTAConfigGenerator):
    def __init__(self, policy_config, postfix_dir, fixup=False):
        self.fixup = fixup
        self.postfix_dir = postfix_dir
        self.policy_file = os.path.join(postfix_dir, "starttls_everywhere_policy")
        MTAConfigGenerator.__init__(self, policy_config)

    def ensure_cf_var(self, var, ideal, also_acceptable):
        """
        Ensure that existing postfix config @var is in the list of @acceptable
        values; if not, set it to the ideal value.
        """
        acceptable = [ideal] + also_acceptable

        l = [(num,line) for num,line in enumerate(self.cf) if line.startswith(var)]
        if not any(l):
            self.additions.append(var + " = " + ideal)
        else:
            values = map(parse_line, l)
            if len(set(values)) > 1:
                if self.fixup:
                    #print "Scheduling deletions:" + `values`
                    conflicting_lines = [num for num,_var,val in values]
                    self.deletions.extend(conflicting_lines)
                    self.additions.append(var + " = " + ideal)
                else:
                    raise ExistingConfigError, "Conflicting existing config values " + `l`
            val = values[0][2]
            if val not in acceptable:
                #print "Scheduling deletions:" + `values`
                if self.fixup:
                    self.deletions.append(values[0][0])
                    self.additions.append(var + " = " + ideal)
                else:
                    raise ExistingConfigError, "Existing config has %s=%s"%(var,val)

    def wrangle_existing_config(self):
        """
        Try to ensure/mutate that the config file is in a sane state.
        Fixup means we'll delete existing lines if necessary to get there.
        """
        self.additions = []
        self.deletions = []
        self.fn = self.find_postfix_cf()
        self.raw_cf = open(self.fn).readlines()
        self.cf = map(string.strip, self.raw_cf)
        #self.cf = [line for line in cf if line and not line.startswith("#")]

        # Check we're currently accepting inbound STARTTLS sensibly
        self.ensure_cf_var("smtpd_use_tls", "yes", [])
        # Ideally we use it opportunistically in the outbound direction
        self.ensure_cf_var("smtp_tls_security_level", "may", ["encrypt","dane"])
        # Maximum verbosity lets us collect failure information
        self.ensure_cf_var("smtp_tls_loglevel", "1", [])
        # Inject a reference to our per-domain policy map
        policy_cf_entry = "texthash:" + self.policy_file

        self.ensure_cf_var("smtp_tls_policy_maps", policy_cf_entry, [])


    def maybe_add_config_lines(self):
        if not self.additions:
            return
        if self.fixup:
            print "Deleting lines:", self.deletions
        self.additions[:0]=["#","# New config lines added by STARTTLS Everywhere","#"]
        new_cf_lines = "\n".join(self.additions) + "\n"
        print "Adding to %s:" % self.fn
        print new_cf_lines
        if self.raw_cf[-1][-1] == "\n":         sep = ""
        else:                                   sep = "\n"

        self.new_cf = ""
        for num, line in enumerate(self.raw_cf):
            if self.fixup and num in self.deletions:
                self.new_cf += "# Line removed by STARTTLS Everywhere\n# " + line
            else:
                self.new_cf += line
        self.new_cf += sep + new_cf_lines

        #print self.new_cf
        f = open(self.fn, "w")
        f.write(self.new_cf)
        f.close()

    def find_postfix_cf(self):
        "Search far and wide for the correct postfix configuration file"
        return os.path.join(self.postfix_dir, "main.cf")

    def set_domainwise_tls_policies(self):
        self.policy_lines = []
        all_acceptable_mxs = self.policy_config.get_acceptable_mxs_dict()
        for address_domain, properties in all_acceptable_mxs.items():
            mx_list = properties.accept_mx_domains
            if len(mx_list) > 1:
                print "Lists of multiple accept-mx-domains not yet supported."
                print "Using MX %s for %s" % (mx_list[0], address_domain)
                print "Ignoring: %s" % (', '.join(mx_list[1:]))
            mx_domain = mx_list[0]
            mx_policy = self.policy_config.get_tls_policy(mx_domain)
            entry = address_domain + " encrypt"
            if mx_policy.min_tls_version.lower() == "tlsv1":
                entry += " protocols=!SSLv2,!SSLv3"
            elif mx_policy.min_tls_version.lower() == "tlsv1.1":
                entry += " protocols=!SSLv2,!SSLv3,!TLSv1"
            elif mx_policy.min_tls_version.lower() == "tlsv1.2":
                entry += " protocols=!SSLv2,!SSLv3,!TLSv1,!TLSv1.1"
            else:
                print mx_policy.min_tls_version
            self.policy_lines.append(entry)

        f = open(self.policy_file, "w")
        f.write("\n".join(self.policy_lines) + "\n")
        f.close()

    ### Let's Encrypt client IPlugin ###

    def prepare(self):
        """Prepare the plugin.
        Finish up any additional initialization.
        :raises .PluginError:
            when full initialization cannot be completed.
        :raises .MisconfigurationError:
            when full initialization cannot be completed. Plugin will
            be displayed on a list of available plugins.
        :raises .NoInstallationError:
            when the necessary programs/files cannot be located. Plugin
            will NOT be displayed on a list of available plugins.
        :raises .NotSupportedError:
            when the installation is recognized, but the version is not
            currently supported.
        """
        # XXX ensure we raise the right kinds of exceptions
        self.postfix_cf_file = self.find_postfix_cf()


    def more_info(self):
        """Human-readable string to help the user.
        Should describe the steps taken and any relevant info to help the user
        decide which plugin to use.
        :rtype str:
        """


    ### Let's Encrypt client IInstaller ###

    def get_all_names(self):
        """Returns all names that may be authenticated.
        :rtype: `list` of `str`
        """

    def deploy_cert(self, domain, _cert_path, key_path, _chain_path, fullchain_path):
        """Deploy certificate.
        :param str domain: domain to deploy certificate file
        :param str cert_path: absolute path to the certificate file
        :param str key_path: absolute path to the private key file
        :param str chain_path: absolute path to the certificate chain file
        :param str fullchain_path: absolute path to the certificate fullchain
            file (cert plus chain)
        :raises .PluginError: when cert cannot be deployed
        """
        self.wrangle_existing_config()
        self.ensure_cf_var("smtpd_tls_cert_file", fullchain_path, [])
        self.ensure_cf_var("smtpd_tls_key_file", key_path, [])
        self.set_domainwise_tls_policies()

    def enhance(self, domain, enhancement, options=None):
        """Perform a configuration enhancement.
        :param str domain: domain for which to provide enhancement
        :param str enhancement: An enhancement as defined in
            :const:`~letsencrypt.constants.ENHANCEMENTS`
        :param options: Flexible options parameter for enhancement.
            Check documentation of
            :const:`~letsencrypt.constants.ENHANCEMENTS`
            for expected options for each enhancement.
        :raises .PluginError: If Enhancement is not supported, or if
            an error occurs during the enhancement.
        """

    def supported_enhancements(self):
        """Returns a list of supported enhancements.
        :returns: supported enhancements which should be a subset of
            :const:`~letsencrypt.constants.ENHANCEMENTS`
        :rtype: :class:`list` of :class:`str`
        """

    def get_all_certs_keys(self):
        """Retrieve all certs and keys set in configuration.
        :returns: tuples with form `[(cert, key, path)]`, where:
            - `cert` - str path to certificate file
            - `key` - str path to associated key file
            - `path` - file path to configuration file
        :rtype: list
        """

    def save(self, title=None, temporary=False):
        """Saves all changes to the configuration files.
        Both title and temporary are needed because a save may be
        intended to be permanent, but the save is not ready to be a full
        checkpoint. If an exception is raised, it is assumed a new
        checkpoint was not created.
        :param str title: The title of the save. If a title is given, the
            configuration will be saved as a new checkpoint and put in a
            timestamped directory. `title` has no effect if temporary is true.
        :param bool temporary: Indicates whether the changes made will
            be quickly reversed in the future (challenges)
        :raises .PluginError: when save is unsuccessful
        """

        self.maybe_add_config_lines()

    def rollback_checkpoints(self, rollback=1):
        """Revert `rollback` number of configuration checkpoints.
        :raises .PluginError: when configuration cannot be fully reverted
        """

    def recovery_routine(self):
        """Revert configuration to most recent finalized checkpoint.
        Remove all changes (temporary and permanent) that have not been
        finalized. This is useful to protect against crashes and other
        execution interruptions.
        :raises .errors.PluginError: If unable to recover the configuration
        """

    def view_config_changes(self):
        """Display all of the LE config changes.
        :raises .PluginError: when config changes cannot be parsed
        """

    def config_test(self):
        """Make sure the configuration is valid.
        :raises .MisconfigurationError: when the config is not in a usable state
        """

    def restart(self):
        """Restart or refresh the server content.
        :raises .PluginError: when server cannot be restarted
        """
        if os.geteuid() != 0:
            os.system("sudo service postfix reload")
        else:
            os.system("service postfix reload")


def usage():
    print ("Usage: %s starttls-everywhere.json /etc/postfix /etc/letsencrypt/live/example.com/" %
          sys.argv[0])
    sys.exit(1)

if __name__ == "__main__":
    import Config as config
    if len(sys.argv) != 4:
        usage()
    c = config.Config()
    c.load_from_json_file(sys.argv[1])
    postfix_dir = sys.argv[2]
    le_lineage = sys.argv[3]
    pieces = [os.path.join(le_lineage, f) for f in (
        "cert.pem", "privkey.pem", "chain.pem", "fullchain.pem")]
    if not os.path.isdir(le_lineage) or not all(os.path.isfile(p) for p in pieces) :
        print "Let's Encrypt directory", le_lineage, "does not appear to contain a valid lineage"
        print
        usage()
    cert, key, chain, fullchain = pieces
    pcgen = PostfixConfigGenerator(c, postfix_dir, fixup=True)
    pcgen.prepare()
    pcgen.deploy_cert(cert, key, chain, fullchain)
    pcgen.save()
    pcgen.restart()
