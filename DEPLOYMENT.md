1. Install Python 3.11

2. Copy diode-flow folder

3. Run:

   chmod +x *.sh

4. Install dependencies:

   ./install_offline.sh

5. Launch UI:

   ./start_ui.sh

6. Transfer file:

   - Open UI
   - Enter file path
   - Select security level
   - Click Start Transfer

7. Output files appear in:

   demo_output/storage/

8. For Local CLI transfer, use the same CLI command:

    python run_demo.py --file myfile.iso