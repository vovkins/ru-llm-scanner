import jenkins.model.Jenkins
import hudson.model.Node
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import hudson.slaves.DumbSlave
import hudson.slaves.JNLPLauncher
import hudson.slaves.RetentionStrategy

def instance = Jenkins.get()
def realm = new HudsonPrivateSecurityRealm(false)
realm.createAccount('scanner-test', System.getenv('SCANNER_JENKINS_ADMIN_PASSWORD'))
instance.setSecurityRealm(realm)
def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
instance.setAuthorizationStrategy(strategy)
instance.setNumExecutors(0)
instance.setNoUsageStatistics(true)
instance.getUpdateCenter().getSites().clear()
instance.addNode(new DumbSlave(
    'scanner-cpu-amd64', 'Disposable native scanner acceptance agent',
    System.getenv('SCANNER_JENKINS_AGENT_ROOT'), '2', Node.Mode.EXCLUSIVE,
    'scanner-cpu-amd64', new JNLPLauncher(), new RetentionStrategy.Always(), []
))
instance.save()
