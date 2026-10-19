echo "Starting Claude in the Claude folder (v7.7)..."

if [ -d /Volumes/GIT ]; then
    cd /Volumes/GIT
fi

cd Claude_2027/SHARED_WORK_FOLDER
claude --continue --dangerously-skip-permissions --model opus
