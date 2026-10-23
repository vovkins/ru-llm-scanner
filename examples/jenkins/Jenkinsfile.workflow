// Trusted scanner installation; never load this pipeline from the scanned repo.
pipeline {
    agent { label 'scanner-cpu-amd64' }
    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 75, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '5'))
    }
    parameters {
        choice(name: 'SCAN_MODE', choices: ['snapshot', 'diff'], description: 'Snapshot B or transition A to B')
        string(name: 'REPOSITORY_NAME', defaultValue: 'prepared-repo', description: 'Prepared clone under the trusted repository root')
        string(name: 'REF_A', defaultValue: '', description: 'Base commit for diff')
        string(name: 'REF_B', defaultValue: 'HEAD', description: 'Target commit')
        string(name: 'CONFIG_NAME', defaultValue: '', description: 'Approved configuration filename')
        string(name: 'BASELINE_NAME', defaultValue: '', description: 'Approved baseline filename')
        booleanParam(name: 'REQUIRE_BASELINE', defaultValue: true, description: 'Require a trusted clean baseline for diff')
    }
    environment {
        SCANNER_HOME = '/opt/ru-llm-scanner'
        SCANNER_ANALYZER_CPUS = '2'
        SCANNER_REPOSITORIES = '/srv/ru-llm-scanner/repositories'
        SCANNER_CONFIGS = '/srv/ru-llm-scanner/configs'
        SCANNER_BASELINES = '/srv/ru-llm-scanner/baselines'
    }
    stages {
        stage('Offline scan') {
            steps {
                deleteDir()
                script {
                    int code = sh(returnStatus: true, script: '''#!/bin/sh
set +x
umask 077
exec python3 "$SCANNER_HOME/examples/jenkins/run_workflow_scan.py"
''')
                    if (code == 1) {
                        unstable('Sensitive-data findings; inspect restricted artifacts')
                    } else if (code != 0) {
                        error('Scan incomplete or infrastructure failure; baseline must not be promoted')
                    }
                }
            }
        }
    }
    post {
        always {
            archiveArtifacts(artifacts: 'scan-results/report.json,scan-results/report.html,scan-status.json', allowEmptyArchive: true)
        }
    }
}
