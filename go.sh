echo "Starting Claude in the Claude folder (v7.5)..."

if [ -d /Volumes/GIT ]; then
    cd /Volumes/GIT
fi

cd CLAUDE_2027/SHARED_WORK_FOLDER
claude --continue --dangerously-skip-permissions --model opus
