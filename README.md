# ZDCurtain Load Remover

Remove load times from your copy of Metroid Dread for Nintendo Switch! 

<p align="center"><img src="./docs/zdcurtain-0.1.0.gif" alt="Example" /></p>

## Major features

ZDCurtain works across all environments:

- Use any version of the game!
- Play on Nintendo Switch 1 or Nintendo Switch 2!
- Works on Nintendo Switch insertable Game Cards, internal digital storage, and microSD / microSD Express Cards!
- Compatible with any timer that allows pausing and resuming using the keyboard

## How does it work?

ZDCurtain works by comparing a screen capture of the game to common comparison images used in Metroid Dread's load screens. If ZDCurtain is confident that what it's seeing is a load screen, it will pause your game timer of choice until the load is complete while accounting for when the load started. It also removes black screen load times by comparing the top third of the game feed to solid black and pausing your game timer until the feed is no longer solid black. 

ZDCurtain eliminates:

- Area transition load times (elevator, tram / train, teleportal, Itorash capsule)
- Black screen load times caused by moving from one room to another, as long as the black screen exists for at least 100 milliseconds
- Load times that occur during hint screens (for example, when first loading the game or when reloading after returning to a checkpoint or save point)
- The load time between the Raven Beak fight and the Raven Beak X cutscene

## Known Limitations

- **You must provide a clean game feed to ZDCurtain in order for it to work.** This means no stream layouts or alerts can obscure the view that ZDCurtain has to the game feed. To launch a clean game feed in OBS, either set your OBS Virtual Camera to the output of your capture card, or right-click your capture card source and click "Open Source Projector", then click "New window". Resize your projector window so that it is *at least* 640x360 in resolution.
- The window that you are capturing from cannot be minimized.
- ZDCurtain is only capable of interacting with the "Real Time" timer in LiveSplit, which means you cannot have a Real-Time Attack (RTA) time and a Loads Removed Time (LRT) at the same time. This will be addressed in a future release.
- ZDCurtain must be able to rapidly pause and resume the timer in order to remove black screen load times. For this reason, ZDCurtain is incompatible with the "Double-Tap Prevention" option in LiveSplit.
- Custom regions cannot be selected at this time.
- ZDCurtain has only been tested under "Default Brightness" in Metroid Dread. Other brightness settings may produce different results.
- ZDCurtain has not been tested with Metroid Dread Randomizer yet. Use at your own risk.

# Installation

Download the latest version from the [Releases page](https://github.com/goth-uhaul/ZDCurtain/releases/latest). Unzip the file and double-click to run.

## Compatibility

ZDCurtain is compatible with Windows 10 and 11.

# Credits

- Created by [jay](https://bsky.app/profile/jayena.hijumpboots.com) using code and concepts from [AutoSplit](https://github.com/Toufool/AutoSplit)
- [may_berry](https://bsky.app/profile/mayberryzoom.bsky.social) for the icon, Dread system knowledge, and LiveSplit usage knowledge
- [Arcanox](https://bsky.app/profile/arcanox.me) for the confidence plateau algorithm advice
- [Vale](https://bsky.app/profile/valefor-m.bsky.social) for creating masks and for testing support
